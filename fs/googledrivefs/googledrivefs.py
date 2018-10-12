from __future__ import absolute_import

from contextlib import contextmanager
from datetime import datetime
from hashlib import md5
from io import BytesIO, SEEK_END
from logging import debug, info
from os import close, remove
from os.path import join as osJoin, splitext
from tempfile import gettempdir, mkstemp

from apiclient.discovery import build
from apiclient.http import MediaFileUpload
from ..base import FS
# from fs.base import FS
from fs.enums import ResourceType
from fs.errors import DirectoryExists, DirectoryExpected, DirectoryNotEmpty, FileExists, FileExpected, InvalidCharsInPath, ResourceNotFound
from fs.info import Info
from fs.iotools import RawWrapper
from fs.mode import Mode
from fs.path import basename, dirname, iteratepath
from fs.subfs import SubFS
from fs.time import datetime_to_epoch, epoch_to_datetime
from httplib2 import FileCache, Http, ServerNotFoundError

def _SafeCacheName(x):
	m = md5()
	m.update(x.encode("utf-8"))
	return m.hexdigest()

def _Escape(name):
	name = name.replace("\\", "\\\\")
	name = name.replace("'", r"\'")
	return name

_fileMimeType = "application/vnd.google-apps.file"
_folderMimeType = "application/vnd.google-apps.folder"
_INVALID_PATH_CHARS = ":\0"

def _CheckPath(path):
	for char in _INVALID_PATH_CHARS:
		if char in path:
			raise InvalidCharsInPath(path)

# TODO - switch to MediaIoBaseUpload and use BytesIO
class _UploadOnClose(RawWrapper):
	def __init__(self, fs, path, parsedMode):
		self.fs = fs
		self.path = path
		self.parentMetadata = self.fs._itemFromPath(dirname(self.path))
		self.thisMetadata = self.fs._itemFromPath(self.path) # may be None
		# keeping a parsed mode separate from the base class's mode member
		self.parsedMode = parsedMode
		fileHandle, self.localPath = mkstemp(prefix="pyfilesystem-googledrive-", suffix=splitext(self.path)[1], text=False)
		close(fileHandle)
		debug(f"self.localPath: {self.localPath}")

		if (self.parsedMode.reading or self.parsedMode.appending) and not self.parsedMode.truncate:
			if self.thisMetadata is not None:
				initialData = self.fs.drive.files().get_media(fileId=self.thisMetadata["id"]).execute()
				debug(f"Read initial data: {initialData}")
				with open(self.localPath, "wb") as f:
					f.write(initialData)
		platformMode = self.parsedMode.to_platform()
		platformMode += ("b" if "b" not in platformMode else "")
		platformMode = platformMode.replace("x", "a")
		super().__init__(f=open(self.localPath, mode=platformMode))
		if self.parsedMode.appending:
			# seek to the end
			self.seek(0, SEEK_END)
			debug("Seeked to end")

	def close(self):
		super().close() # close the file so that it's readable for upload
		if self.parsedMode.writing:
			# google doesn't accept the fractional second part
			now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
			onlineMetadata = {"modifiedTime": now}

			with open(self.localPath, "rb") as f:
				dataToWrite = f.read()
			debug(f"About to upload data: {dataToWrite}")

			if len(dataToWrite) > 0:
				upload = MediaFileUpload(self.localPath, resumable=True)
				if self.thisMetadata is None:
					debug("Creating new file")
					onlineMetadata.update({"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
					request = self.fs.drive.files().create(body=onlineMetadata, media_body=upload)
				else:
					debug("Updating existing file")
					request = self.fs.drive.files().update(fileId=self.thisMetadata["id"], body={}, media_body=upload)

				response = None
				while response is None:
					status, response = request.next_chunk()
					debug(f"{status}: {response}")
				# MediaFileUpload doesn't close it's file handle, so we have to workaround it
				upload._fd.close()
			else:
				onlineMetadata.update({"mime_type": _fileMimeType})
				onlineMetadata.update({"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
				createdFile = self.fs.drive.files().create(
					body=onlineMetadata,
					media_body=self.localPath,
					media_mime_type=_fileMimeType).execute()
				debug(f"Created file: {createdFile}")
		remove(self.localPath)

class GoogleDriveFS(FS):
	def __init__(self, credentials):
		super().__init__()
		# do the authentication outside
		assert credentials is not None and credentials.invalid is False, "Invalid or misssing credentials"

		cache = FileCache(osJoin(gettempdir(), ".httpcache"), safe=_SafeCacheName)
		http = Http(cache, timeout=60)
		http = credentials.authorize(http)
		self.drive = build("drive", "v3", http=http)

		_meta = self._meta = {
			"case_insensitive": True, # it will even let you have 2 identical filenames in the same directory! But the search is case-insensitive
			"invalid_path_chars": _INVALID_PATH_CHARS, # not sure what else
			"max_path_length": None, # don't know what the limit is
			"max_sys_path_length": None, # there's no syspath
			"network": True,
			"read_only": False,
			"supports_rename": False # since we don't have a syspath...
		}

	def __repr__(self):
		return "<GoogleDriveFS>"

	def _childByName(self, parentId, childName):
		# this "name=" clause seems to be case-insensitive, which means it's easier to model this as a case-insensitive filesystem
		query = f"trashed=False and name='{_Escape(childName)}'"
		if parentId is not None:
			query = query +  f" and '{parentId}' in parents"
		result = self.drive.files().list(q=query, fields="files(id,mimeType,kind,name,createdTime,modifiedTime,size)").execute()
		debug(f"_childByName: {result['files']}")
		if len(result["files"]) not in [0, 1]:
			# Google drive doesn't follow the model of a filesystem, really
			# but since most people will set it up to follow the model, we'll carry on regardless
			# and just throw an error when it becomes a problem
			raise RuntimeError(f"Folder with id {parentId} has more than 1 child with name {childName}")
		if len(result["files"]) == 0:
			# debug(f"_childByName: Not found: {parentId}, {childName}")
			return None
		# if result["files"][0]["name"] != childName:
		# 	return None
		# debug(f"_childByName: Found: {result['files'][0]}")
		return result["files"][0]

	def _childrenById(self, parentId):
		query = f"trashed=False"
		if parentId is not None:
			query = query +  f" and '{parentId}' in parents"
		result = self.drive.files().list(q=query, fields="files(id,mimeType,kind,name,createdTime,modifiedTime,size)").execute()
		return result["files"]

	def _itemFromPath(self, path):
		metadata = None
		for component in iteratepath(path):
			# debug(f"component: {component}: {metadata is not None}")
			metadata = self._childByName(metadata["id"] if metadata is not None else None, component)
			if metadata is None:
				return None
		debug(f"_itemFromPath returns {path}: {metadata}")
		return metadata

	def _infoFromMetadata(self, metadata): # pylint: disable=no-self-use
		isFolder = (metadata["mimeType"] == _folderMimeType)
		rfc3339 = "%Y-%m-%dT%H:%M:%S.%fZ"
		rawInfo = {
			"basic": {
				"name": metadata["name"],
				"is_dir": isFolder,
				},
			"details": {
				"accessed": None, # not supported by Google Drive API
				"created": datetime_to_epoch(datetime.strptime(metadata["createdTime"], rfc3339)),
				"metadata_changed": None, # not supported by Google Drive API
				"modified": datetime_to_epoch(datetime.strptime(metadata["modifiedTime"], rfc3339)),
				"size": int(metadata["size"]) if isFolder is False else None, # folders have no size
				"type": ResourceType.directory if isFolder else ResourceType.file
				}
			}
		# there is also file-type-specific metadata like imageMediaMetadata
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			return self._infoFromMetadata(metadata)

	def setinfo(self, path, info): # pylint: disable=too-many-branches
		_CheckPath(path)

	def listdir(self, path):
		_CheckPath(path)
		with self._lock:
			return [x.name for x in self.scandir(path)]

	def makedir(self, path, permissions=None, recreate=False):
		_CheckPath(path)
		with self._lock:
			info(f"makedir: {path}, {permissions}, {recreate}")
			parentMetadata = self._itemFromPath(dirname(path))
			if parentMetadata is None:
				raise ResourceNotFound(path=path)
			childMetadata = self._childByName(parentMetadata["id"], basename(path))
			if childMetadata is not None:
				if recreate is False:
					raise DirectoryExists(path=path)
				else:
					return SubFS(self, path)
			newMetadata = {"name": basename(path), "parents": [parentMetadata["id"]], "mimeType": _folderMimeType}
			newMetadataId = self.drive.files().create(body=newMetadata, fields="id").execute()
			return SubFS(self, path)

	def openbin(self, path, mode="r", buffering=-1, **options):
		_CheckPath(path)
		with self._lock:
			info(f"openbin: {path}, {mode}, {buffering}")
			parsedMode = Mode(mode)
			exists = self.exists(path)
			if parsedMode.exclusive and exists:
				raise FileExists(path)
			elif parsedMode.reading and not parsedMode.create and not exists:
				raise ResourceNotFound(path)
			elif self.isdir(path):
				raise FileExpected(path)
			if parsedMode.writing:
				# make sure that the parent directory exists
				parentDir = dirname(path)
				if self._itemFromPath(parentDir)is None:
					raise ResourceNotFound(parentDir)
			return _UploadOnClose(fs=self, path=path, parsedMode=parsedMode)

	def remove(self, path):
		_CheckPath(path)
		with self._lock:
			info(f"remove: {path}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if metadata["mimeType"] == _folderMimeType:
				raise FileExpected(path=path)
			self.drive.files().delete(fileId=metadata["id"]).execute()

	def removedir(self, path):
		_CheckPath(path)
		with self._lock:
			info(f"removedir: {path}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if metadata["mimeType"] != _folderMimeType:
				raise DirectoryExpected(path=path)
			children = self._childrenById(metadata["id"])
			if len(children) > 0:
				raise DirectoryNotEmpty(path=path)
			self.drive.files().delete(fileId=metadata["id"]).execute()

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		_CheckPath(path)
		with self._lock:
			info(f"remove: {path}, {namespaces}, {page}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			children = self._childrenById(metadata["id"])
			return [self._infoFromMetadata(x) for x in children]

@contextmanager
def setup_test():
	from argparse import Namespace
	from os import environ
	from uuid import uuid4
	from oauth2client import GOOGLE_AUTH_URI, GOOGLE_REVOKE_URI, GOOGLE_TOKEN_URI
	from oauth2client.client import OAuth2WebServerFlow
	from oauth2client.file import Storage
	from oauth2client.tools import run_flow
	storage = Storage(credentialsPath)
	credentials = storage.get()
	if credentials is None or credentials.invalid is True:
		clientId = environ["GOOGLE_DRIVE_CLIENT_ID"]
		clientSecret = environ["GOOGLE_DRIVE_CLIENT_SECRET"]
		credentialsPath = environ["GOOGLE_DRIVE_CREDENTIALS_PATH"]
		scope = "https://www.googleapis.com/auth/drive"
		flow = OAuth2WebServerFlow(clientId, clientSecret, scope=scope, auth_uri=GOOGLE_AUTH_URI, token_uri=GOOGLE_TOKEN_URI, revoke_uri=GOOGLE_REVOKE_URI)
		flags = Namespace()
		flags.logging_level = "INFO"
		flags.noauth_local_webserver = True
		credentials = run_flow(flow, storage, flags)
	fs = GoogleDriveFS(credentials)
	testDir = "/tests/googledrivefs-test-" + uuid4().hex
	try:
		assert fs.exists(testDir) is False
		fs.makedir(testDir)
		yield (fs, testDir)
	finally:
		fs.removedir(testDir)
		fs.close()

def test_directory_creation_and_destruction():
	with setup_test() as testSetup:
		fs, testDir = testSetup

		newDir = testDir + "/testdir"
		assert not fs.exists(newDir), "Bad initial state"
		assert not fs.isdir(newDir), "Bad initial state"
		
		fs.makedir(newDir, recreate=False)
		assert fs.exists(newDir)
		assert fs.isdir(newDir)
		
		try:
			fs.makedir(newDir, recreate=False)
			assert False, "Directory creation should have failed"
		except DirectoryExists:
			pass
		assert fs.exists(newDir)
		assert fs.isdir(newDir)

		fs.makedir(newDir, recreate=True)
		assert fs.exists(newDir)
		assert fs.isdir(newDir)
		
		fs.removedir(newDir)
		assert not fs.exists(newDir)
		assert not fs.isdir(newDir)

def test_update_times():
	with setup_test() as testSetup:
		fs, testDir = testSetup

		path = testDir + "/test.txt"
		with fs.open(path, "w") as f:
			f.write("AAA")
		info1 = fs.getinfo(path)

		with fs.open(path, "a") as f:
			f.write("BBB")
		info2 = fs.getinfo(path)

		assert info2.created == info1.created, "Creation date should be the same"
		assert info2.modified > info1.modified, "Modified date should have increased"

def assert_contents(fs, path, expectedContents):
	with fs.open(path, "r") as f:
		contents = f.read()
		assert contents == expectedContents, f"'{contents}'"

def test_open_modes():
	from contextlib import suppress
	from fs.path import join as fsJoin

	with setup_test() as testSetup:
		fs, testDir = testSetup

		path = fsJoin(testDir, "test.txt")
		with suppress(ResourceNotFound, FileExpected):
			fs.remove(path)
		with fs.open(path, "w") as f:
			f.write("AAA")
		assert_contents(fs, path, "AAA")
		with fs.open(path, "a") as f:
			f.write("BBB")
		assert_contents(fs, path, "AAABBB")
		with fs.open(path, "r+") as f:
			f.seek(1)
			f.write("X")
		assert_contents(fs, path, "AXABBB")
		fs.remove(path)
		assert not fs.exists(path)

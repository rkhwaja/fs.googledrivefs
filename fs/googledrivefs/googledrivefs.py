from __future__ import absolute_import

from datetime import datetime
from io import BytesIO, SEEK_END
from logging import debug, info
from os import close, remove
from os.path import splitext
from tempfile import mkstemp

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from fs.base import FS
from fs.enums import ResourceType
from fs.errors import DirectoryExists, DirectoryExpected, DirectoryNotEmpty, FileExists, FileExpected, InvalidCharsInPath, NoURL, ResourceNotFound, OperationFailed, RemoveRootError
from fs.info import Info
from fs.iotools import RawWrapper
from fs.mode import Mode
from fs.path import basename, dirname, iteratepath
from fs.subfs import SubFS
from fs.time import datetime_to_epoch

_fileMimeType = "application/vnd.google-apps.file"
_folderMimeType = "application/vnd.google-apps.folder"
_sharingUrl = "https://drive.google.com/open?id="
_INVALID_PATH_CHARS = ":\0"

def _Escape(name):
	name = name.replace("\\", "\\\\")
	name = name.replace("'", r"\'")
	return name


def _CheckPath(path):
	for char in _INVALID_PATH_CHARS:
		if char in path:
			raise InvalidCharsInPath(path)


# TODO - switch to MediaIoBaseUpload and use BytesIO
class _UploadOnClose(RawWrapper):
	def __init__(self, fs, path, parsedMode):
		self.fs = fs
		self.path = path
		self.parentMetadata = self.fs._itemFromPath(dirname(self.path))  # pylint: disable=protected-access
		# None here means we'll have to create a new file later
		self.thisMetadata = self.fs._itemFromPath(self.path)  # pylint: disable=protected-access
		# keeping a parsed mode separate from the base class's mode member
		self.parsedMode = parsedMode
		fileHandle, self.localPath = mkstemp(prefix="pyfilesystem-googledrive-", suffix=splitext(self.path)[1],
											 text=False)
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

	def close(self):
		super().close()  # close the file so that it's readable for upload
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
					onlineMetadata.update(
						{"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
					request = self.fs.drive.files().create(body=onlineMetadata, media_body=upload)
				else:
					debug("Updating existing file")
					request = self.fs.drive.files().update(fileId=self.thisMetadata["id"], body={}, media_body=upload)

				response = None
				while response is None:
					status, response = request.next_chunk()
					debug(f"{status}: {response}")
				# MediaFileUpload doesn't close it's file handle, so we have to workaround it (https://github.com/googleapis/google-api-python-client/issues/575)
				upload._fd.close()  # pylint: disable=protected-access
			else:
				fh = BytesIO(b"")
				media = MediaIoBaseUpload(fh, mimetype="application/octet-stream", chunksize=-1, resumable=False)
				if self.thisMetadata is None:
					onlineMetadata.update(
						{"name": basename(self.path), "parents": [self.parentMetadata["id"]], "createdTime": now})
					createdFile = self.fs.drive.files().create(
						body=onlineMetadata,
						media_body=media).execute()
					debug(f"Created empty file: {createdFile}")
				else:
					updatedFile = self.fs.drive.files().update(
						fileId=self.thisMetadata["id"],
						body={},
						media_body=media).execute()
					debug(f"Updated file to empty: {updatedFile}")
		remove(self.localPath)


class GoogleDriveFS(FS):
	def __init__(self, credentials):
		super().__init__()

		self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)

		_meta = self._meta = {
			"case_insensitive": True,
		# it will even let you have 2 identical filenames in the same directory! But the search is case-insensitive
			"invalid_path_chars": _INVALID_PATH_CHARS,  # not sure what else
			"max_path_length": None,  # don't know what the limit is
			"max_sys_path_length": None,  # there's no syspath
			"network": True,
			"read_only": False,
			"supports_rename": False  # since we don't have a syspath...
		}

	def __repr__(self):
		return "<GoogleDriveFS>"

	def _fileQuery(self, query):
		allFields = "files(id,mimeType,kind,name,createdTime,modifiedTime,size,permissions)"
		return self.drive.files().list(q=query, fields=allFields).execute()

	def _childByName(self, parentId, childName):
		# this "name=" clause seems to be case-insensitive, which means it's easier to model this
		# as a case-insensitive filesystem
		if not parentId:
			parentId = 'root'
			# Google drive seems to somehow distinguish it's real root folder from folder named "root" in root folder.
		query = f"trashed=False and name='{_Escape(childName)}' and '{parentId}' in parents"
		result = self._fileQuery(query)
		if len(result["files"]) not in [0, 1]:
			# Google drive doesn't follow the model of a filesystem, really
			# but since most people will set it up to follow the model, we'll carry on regardless
			# and just throw an error when it becomes a problem
			raise RuntimeError(f"Folder with id {parentId} has more than 1 child with name {childName}")
		return result["files"][0] if result["files"] else None

	def _childrenById(self, parentId):
		if not parentId:
			parentId = 'root'
			# Google drive seems to somehow distinguish it's real root folder from folder named "root" in root folder.
		query = f"trashed=False and '{parentId}' in parents"
		result = self._fileQuery(query)
		return result["files"]

	def _itemFromPath(self, path):
		metadata = None
		ipath = iteratepath(path)
		if ipath:
			for child_name in ipath:
				parent_id = metadata["id"] if metadata else None # pylint: disable=unsubscriptable-object
				metadata = self._childByName(parent_id, child_name)
		else:
			metadata = self._childrenById(None) # querying root folder. will return a list, not dict
		return metadata

	def _infoFromMetadata(self, metadata):  # pylint: disable=no-self-use
		isRoot = isinstance(metadata, list)
		isFolder = isRoot or (metadata["mimeType"] == _folderMimeType)
		rfc3339 = "%Y-%m-%dT%H:%M:%S.%fZ"
		rawInfo = {
			"basic": {
				"name": "" if isRoot else metadata["name"],
				"is_dir": isFolder
			},
			"details": {
				"accessed": None,  # not supported by Google Drive API
				"created": None if isRoot else datetime_to_epoch(datetime.strptime(metadata["createdTime"], rfc3339)),
				"metadata_changed": None,  # not supported by Google Drive API
				"modified": None if isRoot else datetime_to_epoch(datetime.strptime(metadata["modifiedTime"], rfc3339)),
				"size": int(metadata["size"]) if "size" in metadata else None, # folders, native google documents etc have no size
				"type": ResourceType.directory if isFolder else ResourceType.file
			},
			"sharing": {
				"id": None if isRoot else metadata["id"],
				"permissions": None if isRoot else metadata["permissions"],
				"is_shared": None if isRoot else len(metadata["permissions"]) > 1
			}
		}
		# there is also file-type-specific metadata like imageMediaMetadata
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):  # pylint: disable=unused-argument
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)
			return self._infoFromMetadata(metadata)

	def setinfo(self, path, info):  # pylint: disable=redefined-outer-name,too-many-branches,unused-argument
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)

	def share(self, path, email=None, role='reader'):
		"""
		Shares item.
		:param path: item path
		:param email: email of gmail-user to share item. If None, will share with anybody.
		:param role: google drive sharing role
		:return: URL
		"""
		_CheckPath(path)
		with self._lock:
			metadata = self._itemFromPath(path)
			if metadata is None or isinstance(metadata, list):
				raise ResourceNotFound(path=path)
			if role not in ('reader', 'writer', 'commenter', 'fileOrganizer', 'organizer', 'owner'):
				raise OperationFailed(path=path, msg=f'unknown sharing role: {role}')
			if email:
				permissions = {'role': role, 'type': 'user', 'emailAddress': email}
			else:
				permissions = {'role': role, 'type': 'anyone'}
			self.drive.permissions().create(fileId=metadata['id'], body=permissions).execute()
			return self.geturl(path)

	def hasurl(self, path, purpose="download"):
		_CheckPath(path)
		if purpose != "download":
			raise NoURL(path, purpose, "No such purpose")
		with self._lock:
			try:
				return self.getinfo(path).get("sharing", "is_shared")
			except ResourceNotFound:
				return False

	def geturl(self, path, purpose="download"): # pylint: disable=unused-argument
		_CheckPath(path)
		if purpose != "download":
			raise NoURL(path, purpose, "No such purpose")
		with self._lock:
			fileInfo = self.getinfo(path)
			if fileInfo.get("sharing", "is_shared") is False:
				raise NoURL(path, purpose, f"{path} is not shared")
			return _sharingUrl + fileInfo.get("sharing", "id")

	def listdir(self, path):
		_CheckPath(path)
		with self._lock:
			return [x.name for x in self.scandir(path)]

	def _create_subdirectory(self, name, parents=None):
		newMetadata = {"name": basename(name), "parents": parents, "mimeType": _folderMimeType}
		self.drive.files().create(body=newMetadata, fields="id").execute()
		return SubFS(self, name)

	def makedir(self, path, permissions=None, recreate=False):
		_CheckPath(path)
		with self._lock:
			info(f"makedir: {path}, {permissions}, {recreate}")
			parentMetadata = self._itemFromPath(dirname(path))

			if isinstance(parentMetadata, list): # adding new folder to root folder
				if not self._childByName(None, path):
					return self._create_subdirectory(path)
				raise DirectoryExists(path=path)

			if parentMetadata is None:
				raise ResourceNotFound(path=path)
			childMetadata = self._childByName(parentMetadata["id"], basename(path))
			if childMetadata is not None:
				if recreate is False:
					raise DirectoryExists(path=path)
				return SubFS(self, path)
			newMetadata = {"name": basename(path), "parents": [parentMetadata["id"]], "mimeType": _folderMimeType}
			_ = self.drive.files().create(body=newMetadata, fields="id").execute()
			return SubFS(self, path)

	def openbin(self, path, mode="r", buffering=-1, **options):  # pylint: disable=unused-argument
		_CheckPath(path)
		with self._lock:
			info(f"openbin: {path}, {mode}, {buffering}")
			parsedMode = Mode(mode)
			exists = self.exists(path)
			if parsedMode.exclusive and exists:
				raise FileExists(path)
			if parsedMode.reading and not parsedMode.create and not exists:
				raise ResourceNotFound(path)
			if self.isdir(path):
				raise FileExpected(path)
			if parsedMode.writing:
				# make sure that the parent directory exists
				parentDir = dirname(path)
				if self._itemFromPath(parentDir) is None:
					raise ResourceNotFound(parentDir)
			return _UploadOnClose(fs=self, path=path, parsedMode=parsedMode)

	def remove(self, path):
		if path == '/':
			raise RemoveRootError()
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
		if path == '/':
			raise RemoveRootError()
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

	def _generate_children(self, children, page):
		if page:
			return (self._infoFromMetadata(x) for x in children[page[0]:page[1]])
		return (self._infoFromMetadata(x) for x in children)

	# non-essential method - for speeding up walk
	def scandir(self, path, namespaces=None, page=None):
		_CheckPath(path)
		with self._lock:
			info(f"scandir: {path}, {namespaces}, {page}")
			metadata = self._itemFromPath(path)
			if metadata is None:
				raise ResourceNotFound(path=path)
			if isinstance(metadata, list): # root folder
				children = self._childrenById(None)
				return self._generate_children(children, page)
			if metadata["mimeType"] != _folderMimeType:
				raise DirectoryExpected(path=path)
			children = self._childrenById(metadata["id"])
			return self._generate_children(children, page)

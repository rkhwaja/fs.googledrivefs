from datetime import datetime
from hashlib import md5
from os.path import join
from tempfile import gettempdir

from apiclient.discovery import build
from fs.base import FS
from fs.errors import FileExpected, ResourceNotFound
from fs.info import Info
from fs.mode import Mode
from fs.path import dirname
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

class GoogleDriveFS(FS):
	def __init__(self, credentials):
		super().__init__()
		# do the authentication outside
		assert credentials is not None and credentials.invalid is False, "Invalid or misssing credentials"

		cache = FileCache(join(gettempdir(), ".httpcache"), safe=_SafeCacheName)
		http = Http(cache, timeout=60)
		http = credentials.authorize(http)
		self.drive = build("drive", "v3", http=http)

		_meta = self._meta = {
			"case_insensitive": False, # I think?
			"invalid_path_chars": ":", # not sure what else
			"max_path_length": None, # don't know what the limit is
			"max_sys_path_length": None, # there's no syspath
			"network": True,
			"read_only": True, # at least until openbin is fully implemented
			"supports_rename": False # since we don't have a syspath...
		}

	def __repr__(self):
		return f"<GoogleDriveFS>"

	def _childByName(self, parentId, childName):
		query = f"trashed=False and name='{_Escape(childName)}'"
		if parentId is not None:
			query = query +  f" and '{parentId}' in parents"
		result = self.drive.files().list(q=query, fields="files(id,mimeType,kind,name,createdTime,modifiedTime,size)").execute()
		assert len(result["files"]) in [0, 1]
		if len(result["files"]) == 0:
			return None
		return result["files"][0]

	def _childrenById(self, parentId):
		query = f"trashed=False"
		if parentId is not None:
			query = query +  f" and '{parentId}' in parents"
		result = self.drive.files().list(q=query, fields="files(id,mimeType,kind,name,createdTime,modifiedTime,size)").execute()

	def _itemFromPath(self, path):
		metadata = None
		if path[0] == "/":
			path = path[1:]
		if path[-1] == "/":
			path = path[:-1]
		for component in path.split("/"):
			metadata = self._childByName(metadata["id"] if metadata is not None else None, component)
			if metadata is None:
				return None
		return metadata

	def _infoFromMetadata(self, metadata): # pylint: disable=no-self-use
		isFolder = (metadata["mimeType"] == "application/vnd.google-apps.folder")
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
				"size": metadata["size"],
				"type": 1 if isFolder else 0
				}
			}
		# there is also file-type-specific metadata like imageMediaMetadata
		return Info(rawInfo)

	def getinfo(self, path, namespaces=None):
		metadata = self._itemFromPath(path)
		if metadata is None:
			raise ResourceNotFound(path=path)
		return self._infoFromMetadata(metadata)

	def setinfo(self, path, info): # pylint: disable=too-many-branches
		pass

	def listdir(self, path):
		pass

	def makedir(self, path, permissions=None, recreate=False):
		pass

	def openbin(self, path, mode="r", buffering=-1, **options):
		pass

	def remove(self, path):
		pass

	def removedir(self, path):
		pass

def setup_test():
	from argparse import Namespace
	from os import environ
	from oauth2client import GOOGLE_AUTH_URI, GOOGLE_REVOKE_URI, GOOGLE_TOKEN_URI
	from oauth2client.client import OAuth2WebServerFlow
	from oauth2client.file import Storage
	from oauth2client.tools import run_flow
	clientId = environ["GOOGLE_DRIVE_CLIENT_ID"]
	clientSecret = environ["GOOGLE_DRIVE_CLIENT_SECRET"]
	credentialsPath = environ["GOOGLE_CREDENTIALS_PATH"]
	scope = "https://www.googleapis.com/auth/drive"
	storage = Storage(credentialsPath)
	credentials = storage.get()
	if credentials is None or credentials.invalid is True:
		flow = OAuth2WebServerFlow(clientId, clientSecret, scope=scope, auth_uri=GOOGLE_AUTH_URI, token_uri=GOOGLE_TOKEN_URI, revoke_uri=GOOGLE_REVOKE_URI)
		flags = Namespace()
		flags.logging_level = "INFO"
		flags.noauth_local_webserver = True
		credentials = run_flow(flow, storage, flags)
	fs = GoogleDriveFS(credentials)
	testDir = "/tests/temp"
	return fs, testDir

def test_getinfo():
	fs, testDir = setup_test()
	info_ = fs.getinfo(testDir + "/test.txt")

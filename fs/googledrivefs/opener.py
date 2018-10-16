__all__ = ["GoogleDriveFSOpener"]

from fs.opener import Opener
from google.oauth2.credentials import Credentials

from .googledrivefs import GoogleDriveFS

class GoogleDriveFSOpener(Opener):
	protocols = ['googledrive']

	def open_fs(self, fs_url, parse_result, writeable, create, cwd):
		_, _, directory = parse_result.resource.partition('/')

		credentials = Credentials(parse_result.params.get("access_token"))
		fs = GoogleDriveFS(credentials)

		if directory:
			return fs.opendir(directory)
		else:
			return fs

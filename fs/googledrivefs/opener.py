__all__ = ["GoogleDriveFSOpener"]

from fs.opener import Opener
import google.auth # pylint: disable=wrong-import-order
from google.oauth2.credentials import Credentials # pylint: disable=wrong-import-order

from .googledrivefs import GoogleDriveFS

class GoogleDriveFSOpener(Opener): # pylint: disable=too-few-public-methods
	protocols = ["googledrive"]

	def open_fs(self, fs_url, parse_result, writeable, create, cwd): # pylint: disable=too-many-arguments
		directory = parse_result.resource

		if "access_token" in parse_result.params:
			# if `access_token` parameters are provided then use them..
			credentials = Credentials(parse_result.params.get("access_token"),
				refresh_token=parse_result.params.get("refresh_token", None),
				token_uri="https://www.googleapis.com/oauth2/v4/token",
				client_id=parse_result.params.get("client_id", None),
				client_secret=parse_result.params.get("client_secret", None))
		else:
			# ..otherwise use default credentials
			credentials, _ = google.auth.default()

		fs = GoogleDriveFS(credentials, parse_result.params.get("root_id", None))

		if directory:
			return fs.opendir(directory)
		return fs

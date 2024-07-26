from __future__ import annotations

__all__ = ['GoogleDriveFSOpener']

from typing import ClassVar

from fs.opener import Opener
import google.auth
from google.oauth2.credentials import Credentials

from .googledrivefs import GoogleDriveFS

class GoogleDriveFSOpener(Opener):
	protocols: ClassVar[list[str]] = ['googledrive']

	def open_fs(self, fs_url, parse_result, writeable, create, cwd): # noqa: ARG002
		directory = parse_result.resource

		if 'access_token' in parse_result.params:
			# if `access_token` parameters are provided then use them..
			credentials = Credentials(parse_result.params.get('access_token'),
				refresh_token=parse_result.params.get('refresh_token', None),
				token_uri='https://www.googleapis.com/oauth2/v4/token', # noqa: S106
				client_id=parse_result.params.get('client_id', None),
				client_secret=parse_result.params.get('client_secret', None))
		else:
			# ..otherwise use default credentials
			credentials, _ = google.auth.default()

		fs = GoogleDriveFS(
			credentials,
			rootId=parse_result.params.get('root_id'),
			driveId=parse_result.params.get('drive_id'),
		)

		if directory:
			return fs.opendir(directory)
		return fs

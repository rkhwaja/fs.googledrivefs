#!/usr/bin/env pipenv run python

from oauth2client import GOOGLE_AUTH_URI, GOOGLE_REVOKE_URI, GOOGLE_TOKEN_URI
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.file import Storage
from oauth2client.tools import run_flow

def Authorize(clientId, clientSecret, credentialsPath):
	storage = Storage(credentialsPath)
	credentials = storage.get()
	if credentials is None or credentials.invalid is True:
		flow = OAuth2WebServerFlow(self.clientId, self.clientSecret, scope="https://www.googleapis.com/auth/drive", auth_uri=GOOGLE_AUTH_URI, token_uri=GOOGLE_TOKEN_URI, revoke_uri=GOOGLE_REVOKE_URI)
		flags = Namespace()
		flags.logging_level = "INFO"
		flags.noauth_local_webserver = True
		credentials = run_flow(flow, storage, flags)
	return credentials

if __name__ == "__main__":
	Authorize(environ["GOOGLEDRIVEFS_TEST_CLIENT_ID"], environ["GOOGLEDRIVEFS_TEST_CLIENT_SECRET"], environ["GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH"])

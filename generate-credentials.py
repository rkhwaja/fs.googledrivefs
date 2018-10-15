#!/usr/bin/env pipenv run python

from argparse import Namespace
from json import dump, load
from os import environ

_SCOPE = "https://www.googleapis.com/auth/drive"

def Authorize(clientId, clientSecret, credentialsPath):
	from oauth2client import GOOGLE_AUTH_URI, GOOGLE_REVOKE_URI, GOOGLE_TOKEN_URI
	from oauth2client.client import OAuth2WebServerFlow
	from oauth2client.file import Storage
	from oauth2client.tools import run_flow

	storage = Storage(credentialsPath)
	credentials = storage.get()
	if credentials is None or credentials.invalid is True:
		flow = OAuth2WebServerFlow(clientId, clientSecret, scope=_SCOPE, auth_uri=GOOGLE_AUTH_URI, token_uri=GOOGLE_TOKEN_URI, revoke_uri=GOOGLE_REVOKE_URI)
		flags = Namespace()
		flags.logging_level = "INFO"
		flags.noauth_local_webserver = True
		credentials = run_flow(flow, storage, flags)
	return credentials

class TokenStorageFile:
	"""Stores the API tokens as a file"""

	def __init__(self, path):
		self.path = path

	def Save(self, token):
		"""Save the given token"""
		with open(self.path, "w") as f:
			dump(token, f)

	def Load(self):
		"""Load and return the token"""
		try:
			with open(self.path, "r") as f:
				return load(f)
		except FileNotFoundError:
			return None

def AuthorizeNew(clientId, clientSecret, tokenStoragePath):
	from requests_oauthlib import OAuth2Session

	tokenStorage = TokenStorageFile(tokenStoragePath)
	authorizationBaseUrl = "https://accounts.google.com/o/oauth2/v2/auth"
	session = OAuth2Session(client_id=clientId, scope=_SCOPE, redirect_uri="https://localhost")
	authorizationUrl, _ = session.authorization_url(authorizationBaseUrl)
	print(f"Go to the following URL and authorize the app: {authorizationUrl}")

	try:
		from pyperclip import copy
		copy(authorizationUrl)
		print("URL copied to clipboard")
	except ImportError:
		pass

	redirectResponse = input("Paste the full redirect URL here:")

	tokenUrl = "https://oauth2.googleapis.com/token"

	token = session.fetch_token(tokenUrl, client_secret=clientSecret, authorization_response=redirectResponse, token_updater=tokenStorage.Save)
	tokenStorage.Save(token)
	return token

if __name__ == "__main__":
	Authorize(environ["GOOGLEDRIVEFS_TEST_CLIENT_ID"], environ["GOOGLEDRIVEFS_TEST_CLIENT_SECRET"], environ["GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH"])

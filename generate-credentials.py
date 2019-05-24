#!/usr/bin/env python

from json import dump, load
from os import environ

from requests_oauthlib import OAuth2Session

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

def Authorize(clientId, clientSecret, tokenStoragePath):
	tokenStorage = TokenStorageFile(tokenStoragePath)
	authorizationBaseUrl = "https://accounts.google.com/o/oauth2/v2/auth"
	_SCOPE = "https://www.googleapis.com/auth/drive"
	session = OAuth2Session(client_id=clientId, scope=_SCOPE, redirect_uri="https://localhost")
	authorizationUrl, _ = session.authorization_url(authorizationBaseUrl, access_type="offline")
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

from contextlib import suppress
from json import load, loads
from logging import info
from os import environ
from unittest import TestCase
from uuid import uuid4

from google.oauth2.credentials import Credentials

from fs.googledrivefs import GoogleDriveFS
from fs.test import FSTestCases

_safeDirForTests = "/test-googledrivefs"

def FullFS():
	if "GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY" in environ:
		credentialsDict = loads(environ["GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY"])
	else:
		with open(environ["GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH"]) as f:
			credentialsDict = load(f)
	credentials = Credentials(credentialsDict["access_token"],
		refresh_token=credentialsDict["refresh_token"],
		token_uri="https://www.googleapis.com/oauth2/v4/token",
		client_id=environ["GOOGLEDRIVEFS_TEST_CLIENT_ID"],
		client_secret=environ["GOOGLEDRIVEFS_TEST_CLIENT_SECRET"])
	return GoogleDriveFS(credentials)

class TestGoogleDriveFS(FSTestCases, TestCase):

	@classmethod
	def setUpClass(cls):
		cls._perRunDir = str(uuid4())
		info(f"Tests are running in {cls._perRunDir}")
		cls.perRunFS = FullFS().opendir(_safeDirForTests).makedir(cls._perRunDir)

	@classmethod
	def tearDownClass(cls):
		with suppress(Exception):
			FullFS().opendir(_safeDirForTests).removetree(cls._perRunDir)

	def make_fs(self):
		self._fullFS = self.__class__.perRunFS
		thisTestDir = str(uuid4())
		info(f"Tests are running in {thisTestDir}")
		return self.__class__.perRunFS.makedir(thisTestDir)

	def destroy_fs(self, fs):
		pass

def testRoot(): # pylint: disable=no-self-use
	fullFS = FullFS()
	info(fullFS.listdir("/"))

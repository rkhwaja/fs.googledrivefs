from os import environ
from unittest import TestCase
from uuid import uuid4

from oauth2client.file import Storage

from fs.googledrivefs import GoogleDriveFS
from fs.test import FSTestCases

class TestGoogleDriveFS(FSTestCases, TestCase):

	def make_fs(self):
		storage = Storage(environ["GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH"])
		credentials = storage.get()
		self.fullFS = GoogleDriveFS(credentials)
		self.testSubdir = "/test-googledrivefs/" + str(uuid4())
		return self.fullFS.makedirs(self.testSubdir)

	def destroy_fs(self, fs):
		self.fullFS.removetree(self.testSubdir)

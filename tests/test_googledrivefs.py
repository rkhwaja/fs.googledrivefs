from json import load, loads
from logging import getLogger
from os import environ
from unittest import TestCase
from uuid import uuid4

from google.oauth2.credentials import Credentials

from fs.errors import DirectoryExpected, FileExists, ResourceNotFound
from fs.googledrivefs import GoogleDriveFS, SubGoogleDriveFS
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
	def make_fs(self):
		self.fullFS = FullFS()
		self.testSubdir = f"{_safeDirForTests}/{uuid4()}"
		_ = self.fullFS.makedirs(self.testSubdir)
		return self.fullFS.opendir(self.testSubdir, factory=SubGoogleDriveFS)

	def destroy_fs(self, _):
		self.fullFS.removetree(self.testSubdir)

	def test_directory_paging(self):
		# default page size is 100
		fileCount = 101
		for i in range(fileCount):
			self.fs.writebytes(str(i), b"x")
		files = self.fs.listdir("/")
		self.assertEqual(len(files), fileCount)

	def test_add_remove_parents(self):
		self.fs.makedir("parent1")
		self.fs.makedir("parent2")
		self.fs.makedir("parent3")
		self.fs.writebytes("parent1/file", b"data1")
		self.fs.writebytes("parent2/file", b"data2")

		# can't link into a parent where there's already a file there
		with self.assertRaises(FileExists):
			self.fs.add_parent("parent1/file", "parent2")

		# can't add a parent which is a file
		with self.assertRaises(DirectoryExpected):
			self.fs.add_parent("parent1/file", "parent2/file")

		# can't add a parent which doesn't exist
		with self.assertRaises(ResourceNotFound):
			self.fs.add_parent("parent1/file2", "parent4")

		# can't add a parent to a file that doesn't exist
		with self.assertRaises(ResourceNotFound):
			self.fs.add_parent("parent1/file2", "parent3")

		# when linking works, the data is the same
		self.fs.add_parent("parent1/file", "parent3")
		self.assert_bytes("parent3/file", b"data1")

		# can't remove a parent from a file that doesn't exist
		with self.assertRaises(ResourceNotFound):
			self.fs.remove_parent("parent1/file2")

		# successful remove_parent call removes one file and leaves the other the same
		self.fs.remove_parent("parent1/file")
		self.assert_not_exists("parent1/file")
		self.assert_bytes("parent3/file", b"data1")

def test_root(): # pylint: disable=no-self-use
	fullFS = FullFS()
	getLogger("fs.googledrivefs").info(fullFS.listdir("/"))

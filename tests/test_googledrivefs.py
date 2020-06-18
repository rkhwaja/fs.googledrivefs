from datetime import datetime
from hashlib import md5
from json import load, loads
from os import environ
from unittest import TestCase
from uuid import uuid4

from google.oauth2.credentials import Credentials

from fs.errors import DestinationExists, DirectoryExpected, FileExists, FileExpected, ResourceNotFound
from fs.googledrivefs import GoogleDriveFS, GoogleDriveFSOpener, SubGoogleDriveFS
from fs.opener import open_fs, registry
from fs.test import FSTestCases
from fs.time import datetime_to_epoch

_safeDirForTests = "/test-googledrivefs"

def CredentialsDict():
	if "GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY" in environ:
		return loads(environ["GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY"])
	with open(environ["GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH"]) as f:
		return load(f)

def FullFS():
	credentialsDict = CredentialsDict()
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
		return self.fullFS.makedirs(self.testSubdir)

	def destroy_fs(self, _):
		self.fullFS.removetree(self.testSubdir)

	def test_hashes(self):
		self.fs.writebytes("file", b"xxxx")
		expectedHash = md5(b"xxxx").hexdigest()
		info_ = self.fs.getinfo("file", "hashes")
		remoteHash = info_.get("hashes", "MD5", None)
		assert expectedHash == remoteHash
		self.fs.makedir("dir")
		info_ = self.fs.getinfo("dir", "hashes")
		self.assertIsNone(info_.get("hashes", "MD5", None))

	def test_shortcut(self):
		self.fs.touch("file")
		self.fs.makedir("parent")
		self.fs.touch("parent/file")
		with self.assertRaises(FileExpected):
			self.fs.add_shortcut("shortcut", "parent")
		with self.assertRaises(ResourceNotFound):
			self.fs.add_shortcut("shortcut", "file2")
		with self.assertRaises(DestinationExists):
			self.fs.add_shortcut("file", "parent/file")
		with self.assertRaises(ResourceNotFound):
			self.fs.add_shortcut("parent2/shortcut", "file")

		self.fs.add_shortcut("shortcut", "file")
		_ = self.fs.getinfo("shortcut")
		self.fs.remove("shortcut")
		assert self.fs.exists("shortcut") is False

	def test_setinfo2(self):
		self.fs.touch("file")
		modifiedTime = datetime(2000, 1, 1, 14, 42, 42)
		self.fs.setinfo("file", {"details": {"modified": datetime_to_epoch(modifiedTime)}})
		info_ = self.fs.getinfo("file")
		assert datetime_to_epoch(info_.modified) == datetime_to_epoch(modifiedTime), f"{info_.modified}"

		createdTime = datetime(1999, 1, 1, 14, 42, 42)
		with self.fs.openbin("file2", "wb", createdDateTime=createdTime) as f:
			f.write(b"file2")
		info_ = self.fs.getinfo("file2")
		assert datetime_to_epoch(info_.created) == datetime_to_epoch(createdTime), f"{info_.created}"

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

	def test_read_write_google_metadata(self):
		filename = "file-for-holding-google-metadata"
		self.fs.writetext(filename, "boogle boggle")

		info_ = self.fs.getinfo(filename)
		self.assertIsNone(info_.get("google", "indexableText"))
		self.assertIsNone(info_.get("google", "appProperties"))

		self.fs.setinfo(filename, {"google": {"appProperties": {"a": "a value"}}})

		info_ = self.fs.getinfo(filename)
		# self.assertEqual(info_.get("google", "indexableText"), "<author>Gilliam</author>")
		self.assertEqual(info_.get("google", "appProperties"), {"a": "a value"})

		self.fs.setinfo(filename, {"google": {"indexableText": "<author>Gillaim</author>"}})

		info_ = self.fs.getinfo(filename)

		self.fs.setinfo(filename, {"google": {"appProperties": {"a": None}}})
		info_ = self.fs.getinfo(filename)
		self.assertIsNone(info_.get("google", "appProperties"))

def test_root():
	fullFS = FullFS()
	fullFS.listdir("/")

def test_makedirs_from_root():
	fullFS = FullFS()

	_ = fullFS.getinfo("/")

	makedirName = f"testgoogledrivefs_{uuid4()}"
	fullFS.makedir(makedirName)
	fullFS.removedir(makedirName)

	makedirsName = f"testgoogledrivefs_{uuid4()}"
	fullFS.makedirs(f"{makedirsName}")
	fullFS.removedir(makedirsName)

	withSubdir = f"testgoogledrivefs_{uuid4()}/subdir"
	fullFS.makedirs(f"{withSubdir}")
	fullFS.removedir(withSubdir)

def test_write_file_to_root():
	filename = f"testgoogledrivefs_{uuid4()}"
	fs = FullFS()
	fs.writebytes(filename, b"")
	assert fs.exists(filename)
	fs.remove(filename)

def test_opener():
	registry.install(GoogleDriveFSOpener())
	client_id = environ["GOOGLEDRIVEFS_TEST_CLIENT_ID"]
	client_secret = environ["GOOGLEDRIVEFS_TEST_CLIENT_SECRET"]
	credentialsDict = CredentialsDict()
	access_token = credentialsDict["access_token"]
	refresh_token = credentialsDict["refresh_token"]

	# Without the initial "/" character, it should still be assumed to relative to the root
	fs = open_fs(f"googledrive://test-googledrivefs?access_token={access_token}&refresh_token={refresh_token}&client_id={client_id}&client_secret={client_secret}")
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == "/test-googledrivefs" # pylint: disable=protected-access

	# It should still accept the initial "/" character
	fs = open_fs(f"googledrive:///test-googledrivefs?access_token={access_token}&refresh_token={refresh_token}&client_id={client_id}&client_secret={client_secret}")
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == "/test-googledrivefs" # pylint: disable=protected-access

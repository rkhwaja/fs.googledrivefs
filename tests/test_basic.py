from __future__ import absolute_import

from contextlib import contextmanager

from pytest import mark

from fs.googledrivefs import GoogleDriveFS

@contextmanager
def setup_test(): # pylint: disable=too-many-locals
	from argparse import Namespace
	from os import environ
	from uuid import uuid4
	from oauth2client import GOOGLE_AUTH_URI, GOOGLE_REVOKE_URI, GOOGLE_TOKEN_URI
	from oauth2client.client import OAuth2WebServerFlow
	from oauth2client.file import Storage
	from oauth2client.tools import run_flow
	credentialsPath = environ["GOOGLE_DRIVE_CREDENTIALS_PATH"]
	storage = Storage(credentialsPath)
	credentials = storage.get()
	if credentials is None or credentials.invalid is True:
		clientId = environ["GOOGLE_DRIVE_CLIENT_ID"]
		clientSecret = environ["GOOGLE_DRIVE_CLIENT_SECRET"]
		scope = "https://www.googleapis.com/auth/drive"
		flow = OAuth2WebServerFlow(clientId, clientSecret, scope=scope, auth_uri=GOOGLE_AUTH_URI, token_uri=GOOGLE_TOKEN_URI, revoke_uri=GOOGLE_REVOKE_URI)
		flags = Namespace()
		flags.logging_level = "INFO"
		flags.noauth_local_webserver = True
		credentials = run_flow(flow, storage, flags)
	fs = GoogleDriveFS(credentials)
	testDir = "/tests/googledrivefs-test-" + uuid4().hex
	try:
		assert fs.exists(testDir) is False
		fs.makedir(testDir)
		yield (fs, testDir)
	finally:
		fs.removedir(testDir)
		fs.close()

@mark.skip("Make the main tests work first")
def test_directory_creation_and_destruction():
	with setup_test() as testSetup:
		fs, testDir = testSetup

		newDir = testDir + "/testdir"
		assert not fs.exists(newDir), "Bad initial state"
		assert not fs.isdir(newDir), "Bad initial state"

		fs.makedir(newDir, recreate=False)
		assert fs.exists(newDir)
		assert fs.isdir(newDir)

		try:
			fs.makedir(newDir, recreate=False)
			assert False, "Directory creation should have failed"
		except DirectoryExists:
			pass
		assert fs.exists(newDir)
		assert fs.isdir(newDir)

		fs.makedir(newDir, recreate=True)
		assert fs.exists(newDir)
		assert fs.isdir(newDir)

		fs.removedir(newDir)
		assert not fs.exists(newDir)
		assert not fs.isdir(newDir)

@mark.skip("Make the main tests work first")
def test_update_times():
	with setup_test() as testSetup:
		fs, testDir = testSetup

		path = testDir + "/test.txt"
		with fs.open(path, "w") as f:
			f.write("AAA")
		info1 = fs.getinfo(path)

		with fs.open(path, "a") as f:
			f.write("BBB")
		info2 = fs.getinfo(path)

		assert info2.created == info1.created, "Creation date should be the same"
		assert info2.modified > info1.modified, "Modified date should have increased"

def assert_contents(fs, path, expectedContents):
	with fs.open(path, "r") as f:
		contents = f.read()
		assert contents == expectedContents, f"'{contents}'"

@mark.skip("Make the main tests work first")
def test_open_modes():
	from contextlib import suppress
	from fs.path import join as fsJoin

	with setup_test() as testSetup:
		fs, testDir = testSetup

		path = fsJoin(testDir, "test.txt")
		with suppress(ResourceNotFound, FileExpected):
			fs.remove(path)
		with fs.open(path, "w") as f:
			f.write("AAA")
		assert_contents(fs, path, "AAA")
		with fs.open(path, "a") as f:
			f.write("BBB")
		assert_contents(fs, path, "AAABBB")
		with fs.open(path, "r+") as f:
			f.seek(1)
			f.write("X")
		assert_contents(fs, path, "AXABBB")
		fs.remove(path)
		assert not fs.exists(path)

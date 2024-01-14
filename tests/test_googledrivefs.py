from datetime import datetime, timedelta, UTC
from hashlib import md5
from io import BytesIO
from json import load, loads
from logging import info
from os import environ
from time import sleep
from unittest import TestCase, skipUnless
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4
from zipfile import ZipFile

from fs.errors import DestinationExists, FileExpected, OperationFailed, ResourceNotFound
from fs.googledrivefs import And, GoogleDriveFS, GoogleDriveFSOpener, MimeTypeEquals, NameEquals, SubGoogleDriveFS
from fs.opener import open_fs, registry
from fs.path import join
from fs.test import FSTestCases
from fs.time import datetime_to_epoch
from google.auth import default
from google.oauth2.credentials import Credentials
from pyngrok import conf, ngrok
from pytest import fixture, mark, raises
from pytest_localserver.http import WSGIServer

_safeDirForTests = '/test-googledrivefs'

def CredentialsDict():
	if 'GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY' in environ:
		return loads(environ['GOOGLEDRIVEFS_TEST_TOKEN_READ_ONLY'])
	if 'GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH' in environ:
		with open(environ['GOOGLEDRIVEFS_TEST_CREDENTIALS_PATH'], encoding='utf-8') as f:
			return load(f)
	return None

def FullFS():
	credentialsDict = CredentialsDict()
	if credentialsDict:
		credentials = Credentials(credentialsDict['access_token'],
			refresh_token=credentialsDict['refresh_token'],
			token_uri='https://www.googleapis.com/oauth2/v4/token', # noqa: S106
			client_id=environ['GOOGLEDRIVEFS_TEST_CLIENT_ID'],
			client_secret=environ['GOOGLEDRIVEFS_TEST_CLIENT_SECRET'])
	else:
		credentials, _ = default()

	return GoogleDriveFS(
		credentials,
		rootId=environ.get('GOOGLEDRIVEFS_TEST_ROOT_ID'),
		driveId=environ.get('GOOGLEDRIVEFS_TEST_DRIVE_ID'),
	)

class simple_app:
	def __init__(self):
		self.notified = False

	def __call__(self, environ_, start_response):
		"""Simplest possible WSGI application"""
		status = '200 OK'
		response_headers = [('Content-type', 'text/plain')]
		start_response(status, response_headers)
		parsedQS = parse_qs(environ_['REQUEST_URI'][2:])
		info(f'Received: {parsedQS}')
		info(f'env: {environ_}')
		if 'validationToken' in parsedQS:
			info('Validating subscription')
			return [parsedQS['validationToken'][0].encode()]
		inputStream = environ_['wsgi.input']
		info(f'Input: {inputStream}')
		info('NOTIFIED')
		self.notified = True
		return ''

@fixture(scope='class')
def testserver(request):
	server = WSGIServer(application=simple_app())
	request.cls.server = server
	server.start()
	yield server
	server.stop()

class PyFsCompatLayer:
    """PyFilesystem2 Python 3.12 compatibility layer.

    Adds a workaround for PyFilesystem2#568:
    https://github.com/PyFilesystem/pyfilesystem2/issues/568
    """

    assertRaisesRegexp = TestCase.assertRaisesRegex

class TestGoogleDriveFS(FSTestCases, TestCase, PyFsCompatLayer):
	def make_fs(self):
		self.fullFS = FullFS()
		self.testSubdir = f'{_safeDirForTests}/{uuid4()}'
		return self.fullFS.makedirs(self.testSubdir)

	def destroy_fs(self, _):
		self.fullFS.removetree(self.testSubdir)

	@mark.usefixtures('testserver')
	def test_webhooks(self):
		port = urlparse(self.server.url).port
		info(f'port={port}')
		info(f'self.server.url={self.server.url}')
		conf.get_default().auth_token = environ['NGROK_AUTH_TOKEN']
		tunnel = ngrok.connect(port, bind_tls=True)
		info(f'tunnel={tunnel}')

		self.fs.touch('touched-file.txt')

		expirationDateTime = datetime.now(UTC) + timedelta(minutes=5)
		subscriptionId = str(uuid4())
		self.fs.watch('touched-file.txt', tunnel.public_url.replace('http://', 'https://'), subscriptionId, expirationDateTime)
		info(f'Watching {subscriptionId}')
		with self.fs.open('touched-file.txt', 'w') as f:
			f.write('Some text')
		info('Touched the file, waiting...')
		# need to wait for some time for the notification to come through, but also process incoming http requests
		for _ in range(10):
			if self.server.app.notified is True:
				break
			sleep(1)
		assert self.server.app.notified is True, f'Not notified: {self.server.app.notified}'

	def test_watch(self):
		with self.assertRaises(ResourceNotFound):
			self.fs.watch('doesnt-exist', 'https://example.com', 'someid')

	def test_hashes(self):
		self.fs.writebytes('file', b'xxxx')
		expectedHash = md5(b'xxxx').hexdigest() # noqa: S324
		info_ = self.fs.getinfo('file', 'hashes')
		remoteHash = info_.get('hashes', 'MD5', None)
		assert expectedHash == remoteHash
		self.fs.makedir('dir')
		info_ = self.fs.getinfo('dir', 'hashes')
		self.assertIsNone(info_.get('hashes', 'MD5', None))

	def test_shortcut(self):
		self.fs.touch('file')
		self.fs.makedir('parent')
		self.fs.touch('parent/file')
		assert self.fs.getinfo('parent/file', ['google']).get('google', 'isShortcut') is False
		with self.assertRaises(FileExpected):
			self.fs.add_shortcut('shortcut', 'parent')
		with self.assertRaises(ResourceNotFound):
			self.fs.add_shortcut('shortcut', 'file2')
		with self.assertRaises(DestinationExists):
			self.fs.add_shortcut('file', 'parent/file')
		with self.assertRaises(ResourceNotFound):
			self.fs.add_shortcut('parent2/shortcut', 'file')

		self.fs.add_shortcut('shortcut', 'file')
		info_ = self.fs.getinfo('shortcut', ['google'])
		assert info_.get('google', 'isShortcut') is True
		self.fs.remove('shortcut')
		assert self.fs.exists('shortcut') is False

	def test_setinfo2(self):
		self.fs.touch('file')
		modifiedTime = datetime(2000, 1, 1, 14, 42, 42)
		self.fs.setinfo('file', {'details': {'modified': datetime_to_epoch(modifiedTime)}})
		info_ = self.fs.getinfo('file')
		assert datetime_to_epoch(info_.modified) == datetime_to_epoch(modifiedTime), f'{info_.modified}'

		createdTime = datetime(1999, 1, 1, 14, 42, 42)
		with self.fs.openbin('file2', 'wb', createdDateTime=createdTime) as f:
			f.write(b'file2')
		info_ = self.fs.getinfo('file2')
		assert datetime_to_epoch(info_.created) == datetime_to_epoch(createdTime), f'{info_.created}'

	def test_directory_paging(self):
		# default page size is 100
		fileCount = 101
		for i in range(fileCount):
			self.fs.writebytes(str(i), b'x')
		files = self.fs.listdir('/')
		self.assertEqual(len(files), fileCount)

	def test_read_write_google_metadata(self):
		filename = 'file-for-holding-google-metadata'
		self.fs.writetext(filename, 'boogle boggle')

		info_ = self.fs.getinfo(filename)
		self.assertIsNone(info_.get('google', 'indexableText'))
		self.assertIsNone(info_.get('google', 'appProperties'))

		self.fs.setinfo(filename, {'google': {'appProperties': {'a': 'a value'}}})
		info_ = self.fs.getinfo(filename)
		self.assertEqual(info_.get('google', 'appProperties'), {'a': 'a value'})

		# Can't read back indexableText but we can check that we didn't wipe out other metadata
		self.fs.setinfo(filename, {'google': {'indexableText': '<author>Gillaim</author>'}})
		info_ = self.fs.getinfo(filename)
		self.assertEqual(info_.get('google', 'appProperties'), {'a': 'a value'})

		self.fs.setinfo(filename, {'google': {'appProperties': {'a': None}}})
		info_ = self.fs.getinfo(filename)
		self.assertIsNone(info_.get('google', 'appProperties'))

	def test_download_google_native_format(self):
		id_ = self.fs.getinfo('').get('sharing', 'id')
		body = {'mimeType': 'application/vnd.google-apps.spreadsheet', 'name': 'test-spreadsheet', 'parents': [id_]}
		self.fs.google_resource().files().create(body=body).execute()
		with BytesIO() as f, raises(OperationFailed):
			self.fs.download('test-spreadsheet', f)
		with BytesIO() as f:
			self.fs.download('test-spreadsheet', f, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
			f.seek(0)
			with ZipFile(f) as zipfile:
				assert '[Content_Types].xml' in zipfile.namelist()

def test_root():
	fullFS = FullFS()
	fullFS.listdir('/')

def test_search():
	fullFS = FullFS()

	directory = f'testgoogledrivefs_{uuid4()}'
	fullFS.makedir(directory)

	filename = f'searchtestfilename_{uuid4()}'
	fullFS.touch(join(directory, filename))

	nameResults = list(fullFS.search(NameEquals(filename)))
	assert len(nameResults) == 1
	assert nameResults[0].name == filename

	textFilename = f'searchtestfilename_{uuid4()}.txt'
	with fullFS.open(join(directory, textFilename), 'w') as f:
		f.write('Some text')

	mimeTypeResults = list(fullFS.search(And(MimeTypeEquals('text/plain'), NameEquals(textFilename))))
	assert len(mimeTypeResults) == 1
	assert mimeTypeResults[0].name == textFilename

	mimeTypeResultsFail = list(fullFS.search(And(MimeTypeEquals('application/pdf'), NameEquals(textFilename))))
	assert len(mimeTypeResultsFail) == 0

	fullFS.removetree(directory)

def test_makedirs_from_root():
	fullFS = FullFS()

	_ = fullFS.getinfo('/')

	makedirName = f'testgoogledrivefs_{uuid4()}'
	fullFS.makedir(makedirName)
	fullFS.removedir(makedirName)

	makedirsName = f'testgoogledrivefs_{uuid4()}'
	fullFS.makedirs(f'{makedirsName}')
	fullFS.removedir(makedirsName)

	parentDir = f'testgoogledrivefs_{uuid4()}'
	fullFS.makedirs(f'{parentDir}/subdir')
	fullFS.removetree(parentDir)

def test_write_file_to_root():
	filename = f'testgoogledrivefs_{uuid4()}'
	fs = FullFS()
	fs.writebytes(filename, b'')
	assert fs.exists(filename)
	fs.remove(filename)

@skipUnless('GOOGLEDRIVEFS_TEST_CLIENT_ID' in environ, 'client id and secret required')
def test_opener():
	registry.install(GoogleDriveFSOpener())
	client_id = environ['GOOGLEDRIVEFS_TEST_CLIENT_ID']
	client_secret = environ['GOOGLEDRIVEFS_TEST_CLIENT_SECRET']
	credentialsDict = CredentialsDict()
	access_token = credentialsDict['access_token']
	refresh_token = credentialsDict['refresh_token']

	# Without the initial "/" character, it should still be assumed to relative to the root
	fs = open_fs(f'googledrive://test-googledrivefs?access_token={access_token}&refresh_token={refresh_token}&client_id={client_id}&client_secret={client_secret}')
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == '/test-googledrivefs' # noqa: SLF001

	# It should still accept the initial "/" character
	fs = open_fs(f'googledrive:///test-googledrivefs?access_token={access_token}&refresh_token={refresh_token}&client_id={client_id}&client_secret={client_secret}')
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == '/test-googledrivefs' # noqa: SLF001

@skipUnless('GOOGLEDRIVEFS_TEST_ROOT_ID' in environ, 'root id required')
def test_opener_with_root_id():
	# (default credentials are used for authentication)

	params = {'root_id': environ['GOOGLEDRIVEFS_TEST_ROOT_ID']}
	if 'GOOGLEDRIVEFS_TEST_DRIVE_ID' in environ:
		params['drive_id'] = environ['GOOGLEDRIVEFS_TEST_DRIVE_ID']
	query = urlencode(params)

	# Without the initial "/" character, it should still be assumed to relative to the root
	fs = open_fs(f'googledrive://test-googledrivefs?{query}')
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == '/test-googledrivefs' # noqa: SLF001

	# It should still accept the initial "/" character
	fs = open_fs(f'googledrive:///test-googledrivefs?{query}')
	assert isinstance(fs, SubGoogleDriveFS), str(fs)
	assert fs._sub_dir == '/test-googledrivefs' # noqa: SLF001

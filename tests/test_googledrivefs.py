from unittest import TestCase
from uuid import uuid4

from fs.googledrivefs import GoogleDriveFS
from fs.test import FSTestCases

class TestGoogleDriveFS(FSTestCases, TestCase):

	def make_fs(self):
		self.rootFS = GoogleDriveFS(credentials)
		return self.rootFS.makedir("/test-googledrivefs-" + str(uuid4()))

	# def destroy_fs(self, fs):
	#     fs.close()
	#     if os.path.exists(self.tempfile):
	#         os.remove(self.tempfile)
	#     del self.tempfile

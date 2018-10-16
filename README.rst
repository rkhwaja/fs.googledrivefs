fs.googledrivefs
================

Implementation of pyfilesystem2 file system for Google Drive

Usage
=====

.. code-block:: python

  fs = GoogleDriveFS(
    credentials=<google-auth credentials>)

  # fs is now a standard pyfilesystem2 file system

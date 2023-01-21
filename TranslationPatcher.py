""" Author: Dominik Beese
>>> Translation Patcher
	createPatches():
		*.*    -> *.*.xdelta

	applyPatches():
		*.*.xdelta -> *.*
	
	distribute():
		*.* -> copy if different
<<<
"""

from os import listdir, walk, sep, remove, rename, makedirs
from os.path import join, exists, isdir, splitext, dirname, basename, normpath, abspath
from shutil import copyfile
from hashlib import md5
import re
from zipfile import ZipFile
from gzip import GzipFile
import json
from tempfile import gettempdir as tempdir
from subprocess import run

PARAMS_FILE = '.ttparams'

# 0: nothing, 1: minimal, 2: default, 3: all
VERBOSE = 2


############
## Params ##
############

class UnsupportedParamException(Exception): pass

class Params:
	prms = None
	
	def loadParams(force_reload = False):
		if not force_reload and Params.prms is not None: return
		try:
			with open(PARAMS_FILE, 'r') as file:
				Params.prms = json.load(file)
		except:
			Params.loadDefaults()
		Params.parseParams()
		Params.verifyParams()
	
	def verifyParams():
		if 'PAT' in Params.prms and Params.prms['PAT']:
			raise UnsupportedParamException('PAT')
	
	def _get(key, default = None):
		Params.loadParams()
		return Params.prms.get(key, default)
	
	def xdeltaFolders(): return Params._get('XDELTA', dict())
	def parentFolders(): return Params._get('PARENT', dict())
	def updateActions(): return Params._get('UPDATE_ACTIONS', list())
	
	def loadDefaults():
		Params.prms = dict()
		# folders to search for files
		Params.prms['XDELTA'] = dict()
		# folders to search for files, patches and saves
		Params.prms['PAT'] = dict()
		# where to put the folders when distributing
		Params.prms['PARENT'] = dict()
	
	def parseParams():
		def parseDir(d): return join(*d.split('/'))
		if 'PARENT' in Params.prms: Params.prms['PARENT'] = {folder: parseDir(dir) for folder, dir in Params.prms['PARENT'].items()}


############
## Helper ##
############

def hash(file):
	""" Calculates the MD5 hash of the given file. """
	hasher = md5()
	with open(file, 'rb') as f: hasher.update(f.read())
	return hasher.digest()

def hashZip(zipfile):
	hasher = md5()
	with ZipFile(zipfile, 'r') as zip:
		for filename in sorted([info.filename for info in zip.infolist()]):
			hasher.update(filename.encode())
			hasher.update(zip.read(filename))
	return hasher.digest()

def extpath(path):
	return normpath(path).split(sep)[1:]

def splitFolder(folder):
		a = folder.split('_')
		parts = {'folder': a[0]}
		if len(a) > 1:
			if re.match('^v\d(\.\d+)*$', a[1]): parts['version'] = a[1]
			else: parts['lang'] = a[1]
		if len(a) > 2: parts['lang'] = a[2]
		return parts

def joinFolder(folder, language, version = None):
	name = folder
	if version: name += '_' + version
	if language: name += '_' + language
	return name

def loopFiles(folders, original_language = None):
	""" Loops over the files in the folders with the given names that
		match the given file types.
		It returns tuples of the folder and edit filename.
		If original_language is given, it addionally returns the
		corresponding original folder.
	"""
	if original_language:
		directories = [splitFolder(dir) for dir in listdir('.') if isdir(dir)]
		# iterate over all defined folders
		for folder, types in folders.items():
			versions = {dir.get('version') for dir in directories if dir['folder'] == folder and dir.get('lang') == original_language}
			if not versions: continue
			
			# iterate over all languages found
			for version, language in [(dir.get('version'), dir.get('lang')) for dir in directories if dir['folder'] == folder and dir.get('version') in versions and dir.get('lang') != original_language]:
				edit_folder = joinFolder(folder, language, version)
				orig_folder = joinFolder(folder, original_language, version)
				if VERBOSE >= 1: print(edit_folder, end=' ', flush=True)
				
				# iterate over all files with a valid file extension
				files = [join(dp, f) for dp, dn, fn in walk(edit_folder) for f in [n for n in fn if splitext(n)[1] in types]]
				if VERBOSE >= 1: print('[%s]' % len(files))
				for edit_file in files:
					yield (folder, edit_file, orig_folder)
	
	else:
		for folder, types in folders.items():
			# iterate over all languages found
			for edit_folder in [dir for dir in listdir('.') if isdir(dir) and splitFolder(dir)['folder'] == folder]:
				if VERBOSE >= 1: print(edit_folder, end=' ', flush=True)
				
				# iterate over all files with a valid file extension
				files = [join(dp, f) for dp, dn, fn in walk(edit_folder) for f in [n for n in fn if splitext(n)[1] in types]]
				if VERBOSE >= 1: print('[%s]' % len(files))
				for edit_file in files:
					yield (folder, edit_file)


###########
## Apply ##
###########

def applyPatches(xdelta, original_language = 'JA', force_override = False):
	ctr = applyXDeltaPatches(xdelta, original_language, force_override)
	print()
	if VERBOSE >= 1 and ctr.get('create', 0) > 0 or VERBOSE >= 3: print('Created %d files.' % ctr.get('create', 0))
	if VERBOSE >= 1: print('Updated %d files.' % ctr.get('update', 0))
	if VERBOSE >= 3: print('Kept %d files.' % ctr.get('keep',   0))

def applyXDeltaPatches(xdelta, original_language, force_override):
	""" Creates .* files from .*.xdelta patches and the original .* files. """
	
	def applyXDelta(orig_file, patch_file, output_file):
		run([abspath(xdelta), '-f', '-d', '-s', orig_file, patch_file, output_file])
	
	ctr = dict()
	folders = dict(zip(Params.xdeltaFolders().keys(), ['.xdelta']*len(Params.xdeltaFolders())))
	for _, patch_file, orig_folder in loopFiles(folders, original_language):
		simplename = extpath(patch_file)
		simplename[-1] = simplename[-1][:-len('.xdelta')]
		msg_prefix = ' * %s:' % join(*simplename)
		
		# find corresponding original file
		orig_file = join(orig_folder, *simplename)
		if not exists(orig_file):
			print(' !', 'Warning: Original file not found:', join(*simplename))
			continue
		
		# define output file
		output_file = patch_file[:-len('.xdelta')]
		
		# check if output file already exists
		if exists(output_file):
			# create temporary output file
			temp_output_file = output_file + '.temp'
			applyXDelta(orig_file, patch_file, temp_output_file)
			# compare output files
			if not force_override and hash(output_file) == hash(temp_output_file):
				# equal -> keep old output file
				if VERBOSE >= 3: print(msg_prefix, 'keep')
				ctr['keep'] = ctr.get('keep', 0) + 1
				remove(temp_output_file)
			else:
				# new -> update output file
				if VERBOSE >= 2: print(msg_prefix, 'update')
				ctr['update'] = ctr.get('update', 0) + 1
				remove(output_file)
				rename(temp_output_file, output_file)
		else:
			# create new output file
			if VERBOSE >= 2: print(msg_prefix, 'create')
			ctr['create'] = ctr.get('create', 0) + 1
			applyXDelta(orig_file, patch_file, output_file)
	return ctr


############
## Create ##
############

def createPatches(xdelta, original_language = 'JA', force_override = False):
	ctr = createXDeltaPatches(xdelta, original_language, force_override)
	print()
	if VERBOSE >= 1 and ctr.get('create', 0) > 0 or VERBOSE >= 3: print('Created %d patches.' % ctr.get('create', 0))
	if VERBOSE >= 1: print('Updated %d patches.' % ctr.get('update', 0))
	if VERBOSE >= 1 and ctr.get('delete', 0) > 0 or VERBOSE >= 3: print('Deleted %d patches.' % ctr.get('delete', 0))
	if VERBOSE >= 3: print('Kept %d patches.' % ctr.get('keep',   0))
	if VERBOSE >= 3: print('Skipped %d files.' % ctr.get('skip',   0))

def createXDeltaPatches(xdelta, original_language, force_override):
	""" Creates .*.xdelta patches from pairs of .* files. """
	
	def createXDelta(orig_file, edit_file, patch_file):
		run([abspath(xdelta), '-f', '-s', orig_file, edit_file, patch_file])
	
	ctr = dict()
	for _, edit_file, orig_folder in loopFiles(Params.xdeltaFolders(), original_language):
		simplename = extpath(edit_file)
		msg_prefix = ' * %s:' % join(*simplename[:-1], simplename[-1]+'.xdelta')
		
		# find corresponding original file
		orig_file = join(orig_folder, *simplename)
		if not exists(orig_file):
			if VERBOSE >= 2: print(' !', 'Warning: Original file not found:', join(*simplename))
			continue
		
		# define patch file
		patch_file = edit_file + '.xdelta'
		
		# compare files
		if hash(orig_file) == hash(edit_file):
			# check if patch exists
			if exists(patch_file):
				if VERBOSE >= 2: print(msg_prefix, 'delete patch')
				ctr['delete'] = ctr.get('delete', 0) + 1
				remove(patch_file)
			else:
				if VERBOSE >= 3: print(msg_prefix, 'skip')
				ctr['skip'] = ctr.get('skip', 0) + 1
			continue
		
		# check if patch already exists
		if exists(patch_file):
			# create temporary patch
			temp_patch_file = patch_file + '.temp'
			createXDelta(orig_file, edit_file, temp_patch_file)
			# compare patches
			if not force_override and hash(patch_file) == hash(temp_patch_file):
				# equal -> keep old patch
				if VERBOSE >= 3: print(msg_prefix, 'keep')
				ctr['keep'] = ctr.get('keep', 0) + 1
				remove(temp_patch_file)
			else:
				# new -> update patch
				if VERBOSE >= 2: print(msg_prefix, 'update')
				ctr['update'] = ctr.get('update', 0) + 1
				remove(patch_file)
				rename(temp_patch_file, patch_file)
		else:
			# create new patch
			if VERBOSE >= 2: print(msg_prefix, 'create')
			ctr['create'] = ctr.get('create', 0) + 1
			createXDelta(orig_file, edit_file, patch_file)
	return ctr


################
## Distribute ##
################

def distribute(languages, version = None, version_only = False, original_language = 'JA', destination_dir = '_dist', force_override = False, verbose = None):
	""" Copies all patches for the given [languages] to the [destination_dir].
		version = None -> (LayeredFS v1.0, CIA v1.0) Copies all v1.0 files
		version = vX.Y, version_only = False -> (LayeredFS vX.Y) Copies all v1.0 files (excluding updated files) and copies all vX.Y files
		version = vX.Y, version_only = True -> (CIA vX.Y) Copies all xV.Y files
	"""
	if verbose is None: verbose = VERBOSE
	if not isinstance(languages, tuple): languages = (languages,)
	if version is None or version == 'v1.0': versions = [None]
	elif version is not None and not version_only: versions = [None, version]
	elif version is not None and version_only: versions = [version]
	ctr = distributeOtherFiles(languages, versions, original_language, destination_dir, force_override, verbose)
	print()
	if VERBOSE >= 1 and ctr.get('add', 0) > 0 or VERBOSE >= 3: print('Added %d files.' % ctr.get('add', 0))
	if VERBOSE >= 1: print('Updated %d files.' % ctr.get('update', 0))
	if VERBOSE >= 3: print('Kept %d files.' % ctr.get('keep',   0))

def distributeOtherFiles(languages, versions, original_language, destination_dir, force_override, VERBOSE):
	""" Copies all *.* files to the given destination. """
	
	def collectFiles(folder, types, ver = None):
		# collect all files ordered by priority language
		files = list() # list of (filename, simplename)
		for lang in languages + (None,): # fallback from folders without language
			for file in [join(dp, f) for dp, dn, fn in walk(joinFolder(folder, lang, ver)) for f in [n for n in fn if splitext(n)[1] in types]]:
				simplename = extpath(file)
				if any(s == simplename for _, s in files): continue
				files.append((file, simplename))
		
		# remove files that are the same as the original files
		orig_folder = joinFolder(folder, original_language)
		files = [(f, s) for f, s in files if not exists(join(orig_folder, *s)) or hash(join(orig_folder, *s)) != hash(f)]
		return files
	
	# iterate over all xdelta folders
	ctr = dict()
	for folder, types in Params.xdeltaFolders().items():
		for ver in versions: # iterate over versions
			# collect files
			files = collectFiles(folder, types, ver)
			if len(versions) > 1 and ver is None: # remove files that are in the original update
				update_files = [extpath(join(dp, f)) for dp, dn, fn in walk(joinFolder(folder, original_language, versions[1])) for f in [n for n in fn if splitext(n)[1] in types]]
				files = [(file, simplename) for file, simplename in files if simplename not in update_files]
			if VERBOSE >= 3 or VERBOSE >= 1 and len(files) > 0: print(joinFolder(folder, ver), '[%d]' % len(files))
			
			# copy collected files
			dest_folder = join(destination_dir, Params.parentFolders()[folder])
			for source_file, simplename in files:
				msg_prefix = ' * %s:' % source_file
				dest_file = join(dest_folder, *simplename)
				
				# check if file already exists
				if exists(dest_file):
					# compare files
					if not force_override and hash(dest_file) == hash(source_file):
						# equal -> keep old file
						if VERBOSE >= 3: print(msg_prefix, 'keep')
						ctr['keep'] = ctr.get('keep', 0) + 1
					else:
						# new -> update file
						if VERBOSE >= 2: print(msg_prefix, 'update')
						ctr['update'] = ctr.get('update', 0) + 1
						remove(dest_file)
						copyfile(source_file, dest_file)
				else:
					# add new file
					if VERBOSE >= 2: print(msg_prefix, 'add')
					ctr['add'] = ctr.get('add', 0) + 1
					makedirs(dirname(dest_file), exist_ok=True)
					copyfile(source_file, dest_file)
	return ctr

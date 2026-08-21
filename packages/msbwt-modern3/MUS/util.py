'''
Created on Nov 1, 2013
@summary: this file mostly contains some auxiliary checks for the command line interface to make sure it's
handed correct file types
@author: holtjma
'''

import argparse as ap
import glob
import gzip
import os

#I see no need for the versions to be different as of now
DESC = "A multi-string BWT package for DNA and RNA."
VERSION = '0.3.0'
PKG_VERSION = VERSION

validCharacters = set(['$', 'A', 'C', 'G', 'N', 'T'])

def readableFastqFile(fileName): 
    '''
    @param filename - must be both an existing and readable fastq file, supported under '.txt' and '.gz' as of now
    '''
    if os.path.isfile(fileName) and os.access(fileName, os.R_OK):
        if fileName.endswith('.txt') or fileName.endswith('.gz') or fileName.endswith('.fastq') or fileName.endswith('.fq'):
            return fileName
        else:
            raise ap.ArgumentTypeError("Wrong file format ('.txt', '.gz', '.fastq', or '.fq' required): '%s'" % fileName)
    else:
        raise ap.ArgumentTypeError("Cannot read file '%s'." % fileName)

'''
TODO: REMOVE UNUSED FUNCTION
'''
def readableNpyFile(fileName):
    if os.path.isfile(fileName) and os.access(fileName, os.R_OK):
        if fileName.endswith('.npy'):
            return fileName
        else:
            raise ap.ArgumentTypeError("Wrong file format ('.npy' required): '%s'" % fileName)
    else:
        raise ap.ArgumentTypeError("Cannot read file '%s'." % fileName)

'''
TODO: REMOVE UNUSED FUNCTION
'''
def writableNpyFile(fileName):
    if os.access(os.path.dirname(fileName), os.W_OK):
        if fileName.endswith('.npy'):
            return fileName
        else:
            raise ap.ArgumentTypeError("Wrong file format ('.npy' required): '%s'." % fileName)
    else:        
        raise ap.ArgumentTypeError("Cannot write file '%s'." % fileName)


def newDirectory(dirName):
    '''
    @param dirName - will make a directory with this name, aka, this must be a new directory
    '''
    #strip any tail '/'
    if dirName[-1] == '/':
        dirName = dirName[0:-1]
    
    if os.path.exists(dirName):
        if len(glob.glob(dirName+'/*')) != 0:
            raise ap.ArgumentTypeError("Non-empty directory already exists: '%s'" % dirName)
    else:
        #this can raise it's own exception
        os.makedirs(dirName)
    return dirName

def existingDirectory(dirName):
    '''
    @param dirName - checks to make sure this directory already exists
    TODO: add checks for the bwt files?
    '''
    #strip any tail '/'
    if dirName[-1] == '/':
        dirName = dirName[0:-1]
    
    if os.path.isdir(dirName):
        return dirName
    else:
        raise ap.ArgumentTypeError("Directory does not exist: '%s'" % dirName)

def newOrExistingDirectory(dirName):
    '''
    @param dirName - the directory could be pre-existing, if not it's created
    '''
    if dirName[-1] == '/':
        dirName = dirName[0:-1]
    
    if os.path.isdir(dirName):
        return dirName
    elif os.path.exists(dirName):
        ap.ArgumentTypeError("'%s' exists but is not a directory" % dirName)
    else:
        os.makedirs(dirName)
        return dirName

def validKmer(kmer):
    '''
    @param kmer - must be contained in the characters used for our sequencing
    '''
    for c in kmer:
        if not (c in validCharacters):
            raise ap.ArgumentTypeError("Invalid k-mer: All characters must be in ($, A, C, G, N, T)")
    return kmer

def fastaIterator(fastaFN):
    '''
    Iterator that yields tuples containing a sequence label and the sequence itself
    @param fastaFN - the FASTA filename to open and parse
    @return - an iterator yielding tuples of the form (label, sequence) from the FASTA file
    '''
    if fastaFN[len(fastaFN)-3:] == '.gz':
        fp = gzip.open(fastaFN, 'rt')
    else:
        fp = open(fastaFN, 'r')
    
    label = ''
    segments = []
    line = ''
    
    for line in fp:
        if line[0] == '>':
            if label != '':
                yield (label, ''.join(segments))
            label = (line.strip('\n')[1:]).split(' ')[0]
            segments = []
        else:
            segments.append(line.strip('\n'))
            
    if label != '' and len(segments) > 0:
        yield (label, ''.join(segments))
    
    fp.close()

def fastqIterator(fastqFN):
    if fastqFN[len(fastqFN)-3:] == '.gz':
        fp = gzip.open(fastqFN, 'rt')
    else:
        fp = open(fastqFN, 'r')
    
    l1 = ''
    seq = ''
    l2 = ''
    quals = ''
    i = 0
    for line in fp:
        if i & 0x3 == 0:
            l1 = line.strip('\n')
        elif i & 0x3 == 1:
            seq = line.strip('\n')
        elif i & 0x3 == 2:
            l2 = line.strip('\n')
        else:
            quals = line.strip('\n')
            yield (l1, seq, l2, quals)
            
            l1 = ''
            seq = ''
            l2 = ''
            quals = ''
        i += 1
    fp.close()


def atomic_replace(source_path, dest_path):
    """Replace dest_path with source_path atomically.

    Python 2.7 has no os.replace.  On POSIX, os.rename is atomic; on
    Windows, os.rename fails if dest_path already exists.  This helper
    removes dest_path first on Windows before renaming.
    """
    if hasattr(os, "replace"):
        os.replace(source_path, dest_path)
    elif os.name == "nt" and os.path.exists(dest_path):
        os.remove(dest_path)
        os.rename(source_path, dest_path)
    else:
        os.rename(source_path, dest_path)


def atomic_write_json(path, document):
    """Write a JSON document atomically: tmp file -> flush -> rename."""
    import json
    dir_name = os.path.dirname(path) or "."
    tmp_path = os.path.join(dir_name, ".tmp_%s.json" % os.getpid())
    with open(tmp_path, "w") as fp:
        json.dump(document, fp, indent=2, sort_keys=True)
        fp.flush()
        try:
            os.fsync(fp.fileno())
        except (OSError, IOError):
            pass
    atomic_replace(tmp_path, str(path))

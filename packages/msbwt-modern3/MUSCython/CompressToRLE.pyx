#!python
#cython: language_level=3str
#cython: boundscheck=False
#cython: wraparound=False
#cython: initializedcheck=False
#cython: profile=False

import numpy as np
cimport numpy as np
import os

from libc.stdio cimport FILE, fopen, fread, fwrite, fclose, stdin

def compressInput(str fn, str bwtDir):
    '''
    This function takes an input file or STDIN stream and converted it to a numpy file containing the Run-Length 
    Encoded (RLE) BWT.
    @param fn - the filename containing the uncompressed BWT string, all symbols must be '$ACGNT\n' or else this
        code will raise an exception; if fn == None, then the code reads from STDIN, allowing for piping
    @param bwtDir - the directory to save our compressed output to; used for loading the BWT later
    @return - None
    '''
    cdef FILE * inputStream
    if fn == None:
        inputStream = stdin
    else:
        # text mode on the input: Windows text-mode reads translate CRLF line
        # endings to '\n', matching the Linux behavior for the same input
        # bytes (the BWT text input is newline-terminated).  The OUTPUT stream
        # below is binary so the RLE payload bytes are never rewritten.
        # encode(): Cython 3str str values must become bytes for fopen().
        inputStream = fopen(fn.encode('UTF-8'), 'r')
    
    if not os.path.exists(bwtDir):
        os.makedirs(bwtDir)
    
    cdef str outputFN = bwtDir+'/comp_msbwt.npy'
    # binary mode: on Windows the C runtime would otherwise translate '\n'
    # (0x0A) bytes inside the RLE payload into '\r\n' pairs, corrupting the
    # output; Linux text mode is already byte-transparent.
    # encode(): Cython 3str str values must become bytes for fopen().
    cdef FILE * outputStream = fopen(outputFN.encode('UTF-8'), 'w+b')
    
    cdef unsigned long BUFFER_SIZE = 1024
    # NOTE: must be a b'' literal. Under Cython language_level=3str a ''
    # literal is unicode, and an explicit <bytes> cast does NOT convert —
    # it silently type-puns the PyObject*, so fread/fwrite would then write
    # through PyBytes_AS_STRING aimed at a PyUnicode object (heap corruption).
    cdef bytes strBuffer = b'\x00' * BUFFER_SIZE
    cdef unsigned char * buffer = strBuffer
    
    #most of the files I've seen are 80 and '\x46', I'm increasing it just in case
    cdef unsigned long headerSize = 96
    cdef str headerHex = '\x56'
    
    cdef unsigned long x
    
    for x in range(0, headerSize-1):
        buffer[x] = 32 #hex value 20 = ' '
    buffer[headerSize-1] = 10 #hex value 0a = '\n'
    fwrite(buffer, 1, headerSize, outputStream)
    
    #set up the translation
    cdef list validSymbols = ['$', 'A', 'C', 'G', 'N', 'T']
    cdef np.ndarray[np.uint8_t, ndim=1, mode='c'] translator = np.array([255]*256, dtype='<u1')
    cdef np.uint8_t [:] translator_view = translator
    
    x = 0
    cdef str c
    for c in validSymbols:
        translator_view[ord(c)] = x
        x += 1
    
    cdef unsigned long readBytes = fread(buffer, 1, BUFFER_SIZE, inputStream)

    cdef unsigned char currSym = buffer[0]
    # M3-R64-COMPRESS4G: run-length accumulator and output-byte counter must
    # be >=64-bit on every platform.  On Win64 LLP64 `unsigned long` is 32-bit,
    # so a single run longer than 2^32-1 symbols wrapped currCount and more
    # than 2^32-1 output bytes wrapped bytesWritten, corrupting the .npy
    # header shape written below.  The persisted RLE encoding is unchanged:
    # each byte carries one 5-bit count chunk, so arbitrary run lengths were
    # already representable -- only the accumulator width was defective.
    cdef np.uint64_t currCount = 0
    cdef unsigned char writeByte
    cdef np.uint64_t bytesWritten = 0
    
    while readBytes > 0:
        for x in range(0, readBytes):
            if currSym == buffer[x]:
                currCount += 1
            else:
                #if it's the new line symbol, we will ignore it
                if translator_view[currSym] == 255:
                    if currSym == 10:
                        pass
                    else:
                        raise Exception('UNEXPECTED SYMBOL DETECTED: '+currSym)
                else:
                    #we are at the end of the run so handle it
                    #print translator_view[currSym], currCount
                    #writeByte = translator_view[currSym]
                    while currCount > 0:
                        writeByte = translator_view[currSym] | ((currCount & 0x1F) << 3)
                        fwrite(&writeByte, 1, 1, outputStream)
                        currCount = currCount >> 5
                        bytesWritten += 1
                        
                    #the symbol is expected
                    currSym = buffer[x]
                    currCount = 1
        
        readBytes = fread(buffer, 1, BUFFER_SIZE, inputStream)
    
    #handle the last run
    #if it's the new line symbol, we will ignore it
    if translator_view[currSym] == 255:
        if currSym == 10:
            pass
        else:
            raise Exception('UNEXPECTED SYMBOL DETECTED: '+currSym)
    else:
        #we are at the end of the run so handle it
        while currCount > 0:
            writeByte = translator_view[currSym] | ((currCount & 0x1F) << 3)
            fwrite(&writeByte, 1, 1, outputStream)
            currCount = currCount >> 5
            bytesWritten += 1
            
        #the symbol is expected
        currSym = 0
        currCount = 0
    
    #we have finished the compression
    fclose(inputStream)
    fclose(outputStream)
    
    #now that we know the total length, fill in the bytes for our header
    # NOTE: the tail literal is ',), }' — it must produce e.g. 'shape': (48,), }
    # int(bytesWritten): exact decimal expansion of the 64-bit counter (a bare
    # str() of a NumPy scalar is formatting-fragile across NumPy versions).
    cdef bytes initialWrite = b'\x93NUMPY\x01\x00' + headerHex.encode('latin1') + b"\x00{'descr': '|u1', 'fortran_order': False, 'shape': (" + str(int(bytesWritten)).encode('ascii') + b',), }'
    buffer = initialWrite

    cdef np.ndarray[np.uint8_t, ndim=1, mode='c'] mmapTemp = np.memmap(bwtDir+'/comp_msbwt.npy', '<u1', 'r+')
    cdef np.uint8_t [:] mmapTemp_view = mmapTemp
    for x in range(0, len(initialWrite)):
        mmapTemp_view[x] = buffer[x]


def rle_counter_boundary_probe(np.uint64_t runLength):
    '''
    M3-R64-COMPRESS4G compiled boundary probe.

    Exercises the exact production scalar types and arithmetic that
    compressInput uses for its run accumulator and output-byte counter:
        bytesWritten += 1 per emitted byte, currCount >>= 5 per chunk,
    plus the downstream header shape-string calculation.  With the repaired
    np.uint64_t declarations this is exact for run lengths far beyond 2^32;
    under the historical `unsigned long` declarations on Win64 LLP64 the
    parameter truncation makes every boundary value beyond 2^32-1 wrong.
    '''
    cdef np.uint64_t currCount = runLength
    cdef np.uint64_t bytesWritten = 0
    while currCount > 0:
        bytesWritten += 1
        currCount = currCount >> 5
    # mirror the production header shape construction
    cdef bytes shapeField = b"(" + str(int(bytesWritten)).encode('ascii') + b",)"
    return (bytesWritten, shapeField)
    
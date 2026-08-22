
cimport numpy as np

# M3-R64 W2 / R64-1: numeric-domain width policy (see
# docs/modernization/NUMERIC_WIDTH_POLICY.md).  Row-index, BWT-length,
# occurrence-count and offset domains are np.uint64_t; `unsigned long` is
# LLP64-32-bit on Windows and is forbidden for those domains.  Symbol values,
# quality bytes and bin geometry stay narrow per policy.

cdef struct bwtRange:
    np.uint64_t l
    np.uint64_t h

cdef class BasicBWT(object):
    cdef np.ndarray numToChar
    cdef unsigned char [:] numToChar_view
    cdef np.ndarray charToNum
    cdef unsigned char [:] charToNum_view
    cdef unsigned long vcLen
    
    cdef str dirName
    cdef np.ndarray bwt
    cdef np.uint8_t [:] bwt_view
    
    # R64-1: BWT length domain -> 64-bit
    cdef np.uint64_t totalSize
    cdef np.ndarray totalCounts
    cdef np.uint64_t [:] totalCounts_view
    
    cdef np.ndarray startIndex
    cdef np.uint64_t [:] startIndex_view
    cdef np.ndarray endIndex
    cdef np.uint64_t [:] endIndex_view
    
    # small domains by policy (bitPower <= 63, binSize = 2**bitPower)
    cdef unsigned long bitPower
    cdef unsigned long binSize
    cdef np.ndarray partialFM
    cdef np.uint64_t[:, :] partialFM_view
    
    # R64-1: iterator cursor/count live in the row-index domain
    cdef np.uint64_t iterIndex
    cdef np.uint64_t iterCount
    cdef unsigned long iterPower
    cdef np.uint8_t iterCurrChar
    cdef np.uint8_t iterCurrCount
    cdef np.uint64_t fileSize
    
    cdef bint lcpsPresent
    cdef np.ndarray lcps
    # M3-R64-LCP repair (W1): F11A persists lcps.npy as <u4.
    cdef np.uint32_t [:] lcps_view
    
    #called during initialization, no reason for a user to need this
    cdef void constructIndexing(BasicBWT self)
    
    #simple queries for basic BWT statistics
    cpdef np.uint64_t getTotalSize(BasicBWT self)
    cpdef np.uint64_t getSymbolCount(BasicBWT self, np.uint8_t symbol)
    cpdef unsigned long getBinBits(BasicBWT self)
    
    #common k-mer queries, both cython and python compatible
    cpdef np.uint64_t countOccurrencesOfSeq(BasicBWT self, object seq, tuple givenRange=*)
    cpdef tuple findIndicesOfStr(BasicBWT self, object seq, tuple givenRange=*)
    cpdef list findIndicesOfRegex(BasicBWT self, object seq, tuple givenRange=*)
    cpdef list findStrWithError(BasicBWT self, object seq, object bonusStr)
    cpdef list findPatternWithError(BasicBWT self, object seq, object bonusStr)
    cpdef set findReadsMatchingSeq(BasicBWT self, object seq, np.uint64_t strLen)
    cpdef list findKmerWithError(BasicBWT self, object seq, np.uint64_t minThresh=*)
    cpdef list findKmerWithErrors(BasicBWT self, object seq, np.uint64_t editDistance, np.uint64_t minThresh=*)
    
    #single character queries, both cython and python compatible
    cpdef np.uint8_t getCharAtIndex(BasicBWT self, np.uint64_t index)
    cpdef np.uint64_t getOccurrenceOfCharAtIndex(BasicBWT self, np.uint8_t sym, np.uint64_t index)
    
    #iterator functions
    cpdef iterInit(BasicBWT self)
    cpdef iterNext(BasicBWT self)
    cdef np.uint8_t iterNext_cython(BasicBWT self) nogil
    
    #full string functions
    cpdef getSequenceDollarID(BasicBWT self, np.uint64_t strIndex, bint returnOffset=*)
    cpdef recoverString(BasicBWT self, np.uint64_t strIndex, bint withIndex=*)
    
    #FM-index related queries
    cdef void fillBin(BasicBWT self, np.uint8_t [:] binToFill, np.uint64_t binID) nogil
    cdef void fillFmAtIndex(BasicBWT self, np.uint64_t [:] fill_view, np.uint64_t index)
    
    #Pileup counting without LCP array
    cpdef np.ndarray[np.uint64_t, ndim=1, mode='c'] countPileup(BasicBWT self, object seq, Py_ssize_t kmerSize)
    
    #these functions are added specifically to reduce the Python overhead of some calls (input/output is a C struct)
    cdef bwtRange getOccurrenceOfCharAtRange(BasicBWT self, np.uint8_t sym, bwtRange inRange) nogil
    cdef bwtRange findRangeOfStr(BasicBWT self, object seq)
    cdef np.ndarray[np.uint64_t, ndim=1, mode='c'] countPileup_c(BasicBWT self, object seq, Py_ssize_t kmerSize)
    cdef np.uint64_t countOccurrencesOfSeq_c(BasicBWT self, unsigned char * seq_view, np.uint64_t seqLen, np.uint64_t mc=*)
    cdef np.uint64_t getOccurrenceOfCharAtIndex_c(BasicBWT self, np.uint8_t sym, np.uint64_t index)
    cdef bwtRange findRangeOfStr_c(BasicBWT self, unsigned char * seq_view, np.uint64_t seqLen)
    
    #the following functions require an LCP array
    cpdef tuple countSeqMatches(BasicBWT self, object seq, Py_ssize_t kmerSize)
    cpdef tuple countStrandedSeqMatches(BasicBWT self, object seq, Py_ssize_t kmerSize)
    cpdef np.ndarray countStrandedSeqMatchesNoOther(BasicBWT self, object seq, Py_ssize_t kmerSize)
    cpdef np.ndarray findKmerThreshold(BasicBWT self, object seq, np.uint64_t threshold)
    cpdef np.ndarray findKmerThresholdStranded(BasicBWT self, object seq, np.uint64_t threshold)
    cpdef np.ndarray findKTOtherStranded(BasicBWT self, object seq, np.uint64_t threshold)


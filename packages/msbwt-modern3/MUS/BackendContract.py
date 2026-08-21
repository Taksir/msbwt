"""Feature 13A - backend capability contract (enhanced-modern2).

This module defines the semantic operations that later compressed backends
must provide or preserve.  The contract deliberately separates:

1. low-level BWT backend primitives (future 13B);
2. higher-level source/read/tag/quality/LCP behavior supplied by the
   existing framework (Features 1-12, Q1, 11A).

A future RLBWT/r-index/move backend does not need to copy Holt's Python
method names.  It needs an adapter that satisfies these semantics and
passes the framework regression tiers.

Feature 13A does NOT choose or implement a backend.
"""


from collections import OrderedDict


CONTRACT_VERSION = 1


BACKEND_PRIMITIVES = OrderedDict([
    (
        "total_size",
        {
            "description": "Return the number of BWT rows/suffixes.",
            "required_by": ["13B.1"],
        },
    ),
    (
        "find_interval",
        {
            "description": (
                "Return the exact half-open FM interval [l,r) for a "
                "pattern; optionally support an existing interval for "
                "backward extension."
            ),
            "required_by": ["13B.1", "Point8A"],
        },
    ),
    (
        "count",
        {
            "description": "Return the exact occurrence count for a pattern.",
            "required_by": ["13B.1", "Points1-8"],
        },
    ),
    (
        "backward_extend",
        {
            "description": (
                "Given I(P), return I(cP) exactly without a full pattern "
                "search."
            ),
            "required_by": ["Point8A", "13B.1"],
        },
    ),
    (
        "access",
        {
            "description": "Return the BWT symbol at one row.",
            "required_by": ["13B.1", "Point10-streaming"],
        },
    ),
    (
        "rank",
        {
            "description": "Return Occ(c, i) over BWT[0:i).",
            "required_by": ["13B.1"],
        },
    ),
    (
        "lf",
        {
            "description": "Apply LF mapping to one BWT row.",
            "required_by": ["13B.2", "Point9-navigation"],
        },
    ),
    (
        "sequence_dollar_id",
        {
            "description": (
                "Resolve an arbitrary BWT row to the stable read/string "
                "terminator identity used by read provenance."
            ),
            "required_by": ["Point9", "13B.2"],
        },
    ),
    (
        "recover_string",
        {
            "description": "Recover one indexed string/read exactly.",
            "required_by": ["Point9", "13B.2"],
        },
    ),
    (
        "locate",
        {
            "description": (
                "Locate suffix/text/read positions for pattern occurrences "
                "without enumerating LF steps from scratch per occurrence."
            ),
            "required_by": ["13B.3", "future matching statistics"],
        },
    ),
])


FRAMEWORK_CAPABILITIES = OrderedDict([
    (
        "source_count",
        {
            "method": "countOccurrencesForSource",
            "description": "Exact Feature-3 count inside one constituent.",
            "stage": "13C",
        },
    ),
    (
        "sparse_sources",
        {
            "method": "nonzeroSources",
            "description": "Feature-4 exact sparse source listing.",
            "stage": "13C",
        },
    ),
    (
        "source_frequency",
        {
            "method": "sourceFrequency",
            "description": "Feature-5 number of sources containing a pattern.",
            "stage": "13C",
        },
    ),
    (
        "top_sources",
        {
            "method": "topSources",
            "description": "Feature-6 top-k sources by exact abundance.",
            "stage": "13C",
        },
    ),
    (
        "subset_count",
        {
            "method": "countSubset",
            "description": "Feature-7 arbitrary source-subset aggregation.",
            "stage": "13C",
        },
    ),
    (
        "group_count",
        {
            "method": "countGroup",
            "description": "Feature-7 metadata-group aggregation.",
            "stage": "13C",
        },
    ),
    (
        "left_extension",
        {
            "method": "extendLeft",
            "description": "Feature-8A exact source-aware left extension.",
            "stage": "13B/13C",
        },
    ),
    (
        "right_extension",
        {
            "method": "extendRight",
            "description": "Feature-8A exact right-extension fallback.",
            "stage": "13B/13C",
        },
    ),
    (
        "read_listing",
        {
            "method": "readsContaining",
            "description": "Feature-9 exact read provenance for matches.",
            "stage": "13D",
        },
    ),
    (
        "tag_values",
        {
            "method": "tagValues",
            "description": "Feature-12 BWT-aligned tag retrieval.",
            "stage": "13D",
        },
    ),
    (
        "tag_counts",
        {
            "method": "tagValueCounts",
            "description": "Feature-12 scalar tag aggregation.",
            "stage": "13D",
        },
    ),
    (
        "quality_recovery",
        {
            "method": "readQuality",
            "description": "Q1 exact FASTQ quality recovery for one read.",
            "stage": "13D",
        },
    ),
    (
        "quality_query",
        {
            "method": "qualityValues",
            "description": (
                "Q1 exact first-base quality values over a matching FM "
                "interval."
            ),
            "stage": "13D",
        },
    ),
    (
        "lcp_access",
        {
            "method": "lcpAt",
            "description": "Feature-11A canonical LCP boundary access.",
            "stage": "13D",
        },
    ),
])


TIERS = OrderedDict([
    (
        "13B.1-search-core",
        [
            "total_size",
            "find_interval",
            "count",
            "backward_extend",
            "access",
            "rank",
        ],
    ),
    (
        "13B.2-navigation",
        [
            "total_size",
            "find_interval",
            "count",
            "backward_extend",
            "access",
            "rank",
            "lf",
            "sequence_dollar_id",
            "recover_string",
        ],
    ),
    (
        "13B.3-locate",
        [
            "total_size",
            "find_interval",
            "count",
            "backward_extend",
            "access",
            "rank",
            "lf",
            "sequence_dollar_id",
            "recover_string",
            "locate",
        ],
    ),
])


class BackendContractError(ValueError):
    pass


class LegacyBWTAdapter(object):
    """Adapt Holt-style BasicBWT method names to the Feature-13 contract."""

    def __init__(self, bwt):
        self.bwt = bwt

    def total_size(self):
        return int(self.bwt.getTotalSize())

    def find_interval(self, seq, given_range=None):
        if given_range is None:
            return tuple(self.bwt.findIndicesOfStr(seq))
        return tuple(
            self.bwt.findIndicesOfStr(
                seq,
                givenRange=given_range,
            )
        )

    def count(self, seq, given_range=None):
        if given_range is None:
            return int(self.bwt.countOccurrencesOfSeq(seq))
        return int(
            self.bwt.countOccurrencesOfSeq(
                seq,
                givenRange=given_range,
            )
        )

    def backward_extend(self, interval, base):
        return self.find_interval(
            base,
            given_range=tuple(interval),
        )

    def access(self, row):
        row = int(row)
        for method_name in (
            "getCharAtIndex",
            "getSymbolAtIndex",
            "access",
        ):
            method = getattr(self.bwt, method_name, None)
            if method is not None:
                return method(row)

        # Some Python test/fallback BWT objects expose a raw BWT array.
        raw = getattr(self.bwt, "bwt", None)
        if raw is not None and not callable(raw):
            return raw[row]

        raise NotImplementedError(
            "legacy BWT object exposes no recognized row-access method"
        )

    def rank(self, symbol, position):
        for method_name in (
            "getOccurrence",
            "getOccurrenceOfCharAtIndex",
            "rank",
        ):
            method = getattr(self.bwt, method_name, None)
            if method is not None:
                return int(method(symbol, int(position)))
        raise NotImplementedError(
            "legacy BWT object exposes no recognized rank method"
        )

    def lf(self, row):
        for method_name in ("getLF", "lf", "LF"):
            method = getattr(self.bwt, method_name, None)
            if method is not None:
                return int(method(int(row)))
        raise NotImplementedError(
            "legacy BWT object exposes no recognized LF method"
        )

    def sequence_dollar_id(self, row, return_offset=False):
        if return_offset:
            return self.bwt.getSequenceDollarID(
                int(row),
                True,
            )
        return int(self.bwt.getSequenceDollarID(int(row)))

    def recover_string(self, dollar_id):
        return self.bwt.recoverString(int(dollar_id))

    def locate(self, seq):
        for method_name in (
            "locate",
            "locateOccurrences",
            "findOccurrences",
        ):
            method = getattr(self.bwt, method_name, None)
            if method is not None:
                return method(seq)
        raise NotImplementedError(
            "legacy BWT object exposes no recognized locate method"
        )

    def has_capability(self, capability):
        mapping = {
            "total_size": ("getTotalSize",),
            "find_interval": ("findIndicesOfStr",),
            "count": ("countOccurrencesOfSeq",),
            "backward_extend": ("findIndicesOfStr",),
            "access": ("getCharAtIndex", "getSymbolAtIndex", "access"),
            "rank": ("getOccurrence", "getOccurrenceOfCharAtIndex", "rank"),
            "lf": ("getLF", "lf", "LF"),
            "sequence_dollar_id": ("getSequenceDollarID",),
            "recover_string": ("recoverString",),
            "locate": ("locate", "locateOccurrences", "findOccurrences"),
        }
        names = mapping.get(capability, ())
        if any(callable(getattr(self.bwt, name, None)) for name in names):
            return True
        if capability == "access":
            raw = getattr(self.bwt, "bwt", None)
            return raw is not None and not callable(raw)
        return False


def _callable_capability(obj, capability):
    checker = getattr(obj, "has_capability", None)
    if callable(checker):
        return bool(checker(capability))
    method = getattr(obj, capability, None)
    return callable(method)


def inspect_backend(adapter):
    """Return which canonical backend primitives are callable."""
    result = {
        "contract_version": CONTRACT_VERSION,
        "capabilities": {},
        "tiers": {},
    }

    for name in BACKEND_PRIMITIVES:
        result["capabilities"][name] = bool(
            _callable_capability(adapter, name)
        )

    for tier_name, required in TIERS.items():
        missing = [
            name
            for name in required
            if not result["capabilities"].get(name, False)
        ]
        result["tiers"][tier_name] = {
            "satisfied": not missing,
            "missing": missing,
        }

    return result


def inspect_framework(msbwt):
    result = {}
    for name, spec in FRAMEWORK_CAPABILITIES.items():
        result[name] = bool(
            callable(getattr(msbwt, spec["method"], None))
        )
    return {
        "contract_version": CONTRACT_VERSION,
        "capabilities": result,
    }


def assert_backend_tier(adapter, tier_name):
    if tier_name not in TIERS:
        raise KeyError("unknown backend tier: %s" % tier_name)

    missing = [
        name
        for name in TIERS[tier_name]
        if not _callable_capability(adapter, name)
    ]
    if missing:
        raise BackendContractError(
            "backend does not satisfy %s; missing %s"
            % (tier_name, ", ".join(missing))
        )
    return True


def contract_document():
    """Return a JSON-serializable description of the contract."""
    return {
        "contract_version": CONTRACT_VERSION,
        "backend_primitives": BACKEND_PRIMITIVES,
        "framework_capabilities": FRAMEWORK_CAPABILITIES,
        "tiers": TIERS,
    }

"""Market adviser for US stocks, India equities and India F&O.

Every value served from here comes from a real source and carries its provenance
(source, as_of, kind). Nothing is generated: when a source is down the value is
`unavailable` and the analysis that needs it is skipped.
"""

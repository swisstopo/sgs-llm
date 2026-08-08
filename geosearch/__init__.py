"""Semantic geodata search over the swisstopo catalogue: FAISS + DuckDB + a CPU
embedding model, with the LLM as a second-stage filter.

Build the index once (`python -m geosearch.build`), then serve it
(`python -m geosearch.server`).
"""

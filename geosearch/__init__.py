"""Semantic geodata search over the swisstopo catalogue: FAISS + DuckDB + Bedrock
embeddings, with the LLM as a second-stage filter.

Build the index once (`python -m geosearch.build`), then serve it
(`python -m geosearch.server`).
"""

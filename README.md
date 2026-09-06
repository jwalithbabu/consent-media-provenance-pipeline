# Consent-Based Media Provenance Pipeline

An end-to-end command-line pipeline that:

1. detects a face in a local image and creates a local similarity signature,
2. performs a genuine reverse-image search for the same or near-duplicate media,
3. retrieves the discovered page metadata and content fingerprint, and
4. anchors that evidence in a tamper-evident local chain that can be re-verified later.

This is intentionally a **media provenance** tool, not a person-identification tool. It does not infer a person’s identity, build a face database, or search the web for people by face. The face stage is limited to processing the image supplied by the user; the web stage searches for the same/near-duplicate media through a reverse-image provider.

## Requirements

- Python 3.11+
- A local image containing at least one reasonably visible face
- A public URL for the same image, because the default reverse-search provider receives a URL rather than the local file
- Network access for reverse search and evidence retrieval

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the complete pipeline

The default provider is Google Lens through its public image-URL flow. The input image is not uploaded by this project; only the explicit `--image-url` is sent to the provider.

```bash
python -m pipeline.cli run \
  --image ./samples/input.jpg \
  --image-url https://example.com/input.jpg \
  --chain chain/chain.json \
  --output-dir runs
```

The command writes:

- `runs/<run-id>/face.json` — detector output and local signature
- `runs/<run-id>/search.json` — raw candidate metadata returned by the provider
- `runs/<run-id>/evidence.json` — selected result, source URL, retrieval metadata, and hashes
- `chain/chain.json` — the local append-only chain

The first external result returned by the real search provider is selected. No URL is pre-seeded in the code.

### Optional SerpApi provider

For a structured Google Lens API response, configure `SERPAPI_KEY` through the environment/secrets manager, then run:

```bash
SERPAPI_KEY=... python -m pipeline.cli run \
  --image ./samples/input.jpg \
  --image-url https://example.com/input.jpg \
  --provider serpapi
```

Do not paste API keys into source files or chat.

## Re-verify the blockchain record

The default chain is a simulated local blockchain. Each block stores:

- an index,
- a UTC timestamp,
- the previous block hash,
- the SHA-256 hash of the saved evidence JSON,
- the discovered source URL, and
- its own SHA-256 block hash.

This satisfies the tamper-evident local-chain option: changing either a prior block or the evidence file causes verification to fail.

Verify only the chain links:

```bash
python -m pipeline.cli verify --chain chain/chain.json
```

Verify both the chain and an evidence file against its anchor:

```bash
python -m pipeline.cli verify \
  --chain chain/chain.json \
  --evidence runs/<run-id>/evidence.json
```

Expected success output includes `"valid": true` and `"evidence_match": true`.

## Design and privacy limitations

- The Haar detector and normalized face signature are local computer-vision features, not a person-identifying biometric model.
- A face scan alone cannot be used to query arbitrary social profiles. The web stage is reverse-image search for the same media and requires an explicit public image URL.
- Search engines may return no match, block automated requests, or return pages that require login. The pipeline reports those failures instead of substituting a hardcoded result.
- A local chain is not a public consensus blockchain. It provides an auditable, tamper-evident record for this demo. For public notarization, replace `pipeline/chain.py` with a testnet adapter that stores the same evidence hash.
- Retrieved page bodies are fingerprinted, not copied into the chain. A later retrieval can be compared to the recorded URL, status, byte count, and SHA-256 digest.
- Always obtain consent and follow the terms of service and privacy rules of the image owner, search provider, and source platform.
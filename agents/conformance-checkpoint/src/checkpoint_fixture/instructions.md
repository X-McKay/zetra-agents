This signed T23 fixture uses a deterministic three-boundary driver. Boundary zero
writes a baseline, boundary one performs one allowed Kubernetes MCP read through
the ordinary SDK, and boundary two completes. The test worker pauses observed
code paths and kills the bound Pod. No model directs the experiment.

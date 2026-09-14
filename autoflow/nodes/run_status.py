from autoflow.registry import NodeType


def status(ctx, node_id, inputs):
    ctx.engine.status_text = inputs["text"]
    return {}, "then"


def manual(ctx, node_id, inputs):
    choice = ctx.engine.manual_interaction(inputs["prompt"])
    return {}, choice


NODES = [NodeType("SetRunStatus", {"text": "string"}, {}, ("then",), status,
    "Set the running overlay's status text. Empty text restores automatic node status.",
    defaults={"text": ""}, title="Set Run Status", category="Flow"),
    NodeType("ManualInteraction", {"prompt": "string"}, {}, ("success", "failed"), manual,
        "Wait for a manual correction. Continue follows Success; Ignore follows Failed. Stop cancels the run. Requires the editor or desktop app.",
        defaults={"prompt": "Please correct the entry, then click Continue. Use Ignore to flag it for later review."},
        title="Manual Interaction", category="Flow")]

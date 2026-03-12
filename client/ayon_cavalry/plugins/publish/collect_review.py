import pyblish.api


class CollectReview(pyblish.api.ContextPlugin):
    """Add review to families if instance created with 'mark_for_review'."""

    label = "Collect Review"
    hosts = ["cavalry"]
    order = pyblish.api.CollectorOrder + 0.1
    settings_category = "cavalry"

    def process(self, context):
        for instance in context:
            creator_attributes = instance.data.get("creator_attributes") or {}
            if (
                creator_attributes.get("mark_for_review")
                and "review" not in instance.data.get("families", [])
            ):
                instance.data.setdefault("families", []).append("review")

from __future__ import annotations


class SyncService:
    def __init__(self, config, database):
        self.config = config
        self.database = database
        self.last_result = "idle"

    def status(self) -> dict:
        summary = self.database.upload_status()
        summary["last_result"] = self.last_result
        summary["enabled"] = self.config.sync.enabled
        return summary

    def force_sync(self) -> dict:
        if not self.config.sync.enabled:
            self.last_result = "disabled"
            return {"ok": False, "message": "sync is disabled in this phase scaffold"}
        self.last_result = "queued"
        return {"ok": True, "message": "sync worker scaffold acknowledged request"}


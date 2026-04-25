
export type SyncJob = {
    id: string;
    name: string;
    status: SyncJobStatus;
    lastRun: string;
    duration: string;
    selected?: boolean;
};

export type SyncJobStatus = "Running" | "Success" | "Failed";
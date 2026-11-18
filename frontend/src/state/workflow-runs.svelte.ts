class WorkflowRuns {
  revision = $state(0);

  changed(): void {
    this.revision++;
  }
}

export const workflowRuns = new WorkflowRuns();

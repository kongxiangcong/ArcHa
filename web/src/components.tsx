export const labels: Record<string, string> = {
  result_failed: "结果未通过",
  result_recorded: "结果已记录",
  recorded: "已记录",
  context: "研究约定",
  system: "工作结果",
  reviewer: "独立审核",
  active: "运行记录中",
  paused: "已暂停",
  closed: "已结束",
  blocked: "需要处理",
  failed: "调用失败",
  cancelled: "已取消",
  unknown: "结果待确认",
  waiting: "等待",
  executing: "执行结果待确认",
  evaluating: "评价结果待确认",
  pending_evaluation: "待评价",
  pending_feedback: "待反馈",
  completed: "已完成",
  pending: "已派发，结果待确认",
  finished: "调用已结束",
  onboard: "研究准备",
  ready: "准备就绪",
  external_blocked: "准备受外部条件阻塞",
  designer: "Designer",
  expert: "Expert",
  evaluator: "Evaluator",
};
export function label(value?: string | null) {
  return value ? (labels[value] ?? value) : "尚无记录";
}
export function time(value?: string | null) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "时间未提供";
}
export function Badge({ value }: { value: string }) {
  return <span className={`badge tone-${value}`}>{label(value)}</span>;
}
export function Alert({ error, stale }: { error?: string; stale?: boolean }) {
  return error ? (
    <div className="notice" role="status">
      {stale ? "更新失败，保留最后已知内容。" : "读取失败。"}
      {error}
    </div>
  ) : null;
}

export function preparationLabel(value: string) {
  return (
    (
      {
        pending: "准备尚未就绪",
        ready: "准备就绪",
        unknown: "准备状态待确认",
        external_blocked: "准备受外部条件阻塞",
        accounting_unknown: "准备计量待确认",
        budget_exhausted: "准备额度已用尽",
      } as Record<string, string>
    )[value] ?? label(value)
  );
}

/** 加载中 / 错误 / 空数据 三种诚实状态的统一展示。 */

export function Loading({ text = "加载中…" }: { text?: string }) {
  return <div className="state-box loading">{text}</div>;
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="state-box error">
      <strong>加载失败</strong>
      <p>{message}</p>
    </div>
  );
}

export function Empty({ text }: { text: string }) {
  return <div className="state-box empty">{text}</div>;
}
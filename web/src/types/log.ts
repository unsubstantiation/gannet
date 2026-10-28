export type LogData = {
  totalLines: number;
  lines: string[];
};

export type LogSeverity = "info" | "warning" | "error" | "debug";

export type LogLine = {
  dateStamp: string;
  severity: LogSeverity;
  section: string;
  content: string;
};

export const logTypes = ["gannet", "go2rtc", "websocket"] as const;
export type LogType = (typeof logTypes)[number];

export type LogSettingsType = {
  disableStreaming: boolean;
};

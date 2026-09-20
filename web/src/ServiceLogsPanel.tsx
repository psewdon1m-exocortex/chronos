import { useEffect, useRef } from "react";
import { mountServiceLogs, type ServiceLogsOptions } from "./service-logs.js";
import "./service-logs.css";
export function ServiceLogsPanel({ base, download, beforeParam }: ServiceLogsOptions) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (element.current) return mountServiceLogs(element.current, { base, ...(download ? { download } : {}), ...(beforeParam ? { beforeParam } : {}) });
  }, [base, download, beforeParam]);
  return <div ref={element} />;
}

import { useEffect, useRef } from "react";
import { mountBackupPolicy, type BackupPolicyOptions } from "./backup-policy.js";
import "./service-agents.css";

export function BackupPolicyPanel({ service, base, headers }: BackupPolicyOptions) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (element.current) return mountBackupPolicy(element.current, { service, base, headers });
  }, [service, base, headers]);
  return <div ref={element} />;
}

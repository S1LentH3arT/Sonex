import { Icon } from "./Icon";
import type { ActivityEvent } from "./protocol";

export function ActivityLog({
  activities,
}: {
  activities: ActivityEvent[];
}) {
  const completed = activities.filter((activity) => activity.status !== "pending").length;
  return (
    <details className="activity-log">
      <summary>
        <Icon name="activity" size={15} />
        <span>Agent activity</span>
        <small>
          {completed}/{activities.length} complete
        </small>
        <Icon className="activity-chevron" name="down" size={14} />
      </summary>
      <ol>
        {activities.map((activity) => (
          <li className={`activity-row ${activity.status || "pending"}`} key={activity.id}>
            <Icon
              name={activity.status === "error" ? "error" : activity.status === "success" ? "check" : "sparkles"}
              size={14}
            />
            <div>
              <span>{activity.title}</span>
              {activity.detail && <small>{activity.detail}</small>}
            </div>
            <small className="activity-result">
              {activity.status === "success"
                ? "Done"
                : activity.status === "error"
                  ? "Failed"
                  : "Running"}
            </small>
          </li>
        ))}
      </ol>
    </details>
  );
}

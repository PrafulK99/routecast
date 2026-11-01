import { describeError } from '../api/errorMessages'

interface Props {
  error: unknown
  onRetry: () => void
}

export function ErrorPanel({ error, onRetry }: Props) {
  const { message, fields, requestId } = describeError(error)
  const fieldMessages = Object.entries(fields).flatMap(([field, messages]) =>
    messages.map((text) => `${field.replace(/[._]/g, ' ')}: ${text}`),
  )

  return (
    <div className="error-panel" role="alert">
      <p>
        <strong>
          <span aria-hidden="true">⚠</span> {message}
        </strong>
      </p>
      {fieldMessages.length > 0 && (
        <ul>
          {fieldMessages.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      {requestId && <p className="request-id">Request id: {requestId}</p>}
      <button type="button" onClick={onRetry}>
        Try again
      </button>
    </div>
  )
}

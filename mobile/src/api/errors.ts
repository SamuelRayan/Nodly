/** An API failure: the backend's problem+json `code` (or a client-side one), plus the HTTP
 * status (0 when the request never got an answer). Screens show t(`errors.${code}`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string | undefined;
  readonly body: Record<string, unknown> | undefined;

  constructor(status: number, code: string, detail?: string, body?: Record<string, unknown>) {
    super(detail ?? code);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.body = body;
  }

  static fromResponse(response: Response, body: unknown): ApiError {
    const problem = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
    const code = typeof problem.code === 'string' ? problem.code : `http_${response.status}`;
    const detail = typeof problem.detail === 'string' ? problem.detail : undefined;
    return new ApiError(response.status, code, detail, problem);
  }

  static network(cause: unknown): ApiError {
    return new ApiError(0, 'network_error', cause instanceof Error ? cause.message : undefined);
  }

  /** The first field error of a 422 validation problem, e.g. "invalid_timezone". */
  get fieldErrorType(): string | undefined {
    const errors = this.body?.errors;
    if (Array.isArray(errors) && errors.length > 0) {
      const first = errors[0] as { type?: unknown };
      return typeof first.type === 'string' ? first.type : undefined;
    }
    return undefined;
  }
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code);
}

import type { AftersalesErrorBody, AftersalesErrorCode } from '../../shared/aftersales.js';

/** A client-facing error with an HTTP status and a safe pt-BR message. */
export class ApiError extends Error {
  constructor(
    readonly status: 400 | 404 | 409,
    readonly code: AftersalesErrorCode,
    message: string,
    readonly param?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }

  toBody(): AftersalesErrorBody {
    return { error: { code: this.code, message: this.message, ...(this.param ? { param: this.param } : {}) } };
  }
}

export const invalid = (param: string, message: string): ApiError =>
  new ApiError(400, 'invalid_parameter', message, param);

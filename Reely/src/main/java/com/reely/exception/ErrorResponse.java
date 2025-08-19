package com.reely.exception;

import com.reely.common.enums.ErrorCode;
import lombok.AllArgsConstructor;
import lombok.Getter;

import java.time.LocalDateTime;
@Getter
@AllArgsConstructor
public class ErrorResponse {
    private int status;
    private String error;
    private String message;
    private LocalDateTime timestamp;

    public static ErrorResponse of(ErrorCode errorCode, String customMessage) {
        return new ErrorResponse(
                errorCode.getStatus().value(),
                errorCode.getStatus().name(),
                customMessage != null ? customMessage : errorCode.getMessage(),
                LocalDateTime.now()
        );
    }
}

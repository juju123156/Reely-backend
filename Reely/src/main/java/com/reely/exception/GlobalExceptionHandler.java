package com.reely.exception;

import com.reely.dto.ResponseDto;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.HashMap;
import java.util.Map;

@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(CustomException.class)
    public ResponseEntity<ResponseDto<Object>> handleCustomException(CustomException ex) {
        return ResponseEntity
                .status(HttpStatus.BAD_REQUEST)
                .body(ResponseDto.builder()
                        .success(false)
                        .message(ex.getMessage())
                        .data(null)
                        .errorCode(ex.getErrorCode())
                        .build()
                );
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> handleValidationExceptions(MethodArgumentNotValidException ex) {
        Map<String, String> errors = new HashMap<>();
        ex.getBindingResult().getFieldErrors().forEach(error ->
                errors.put(error.getField(), error.getDefaultMessage())
        );
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(errors);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ResponseDto<Object>> handleException(Exception ex) {
        return ResponseEntity
                .status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ResponseDto.builder()
                        .success(false)
                        .message(ErrorCode.INTERNAL_ERROR.getMessage())
                        .data(null)
                        .errorCode(ErrorCode.INTERNAL_ERROR)
                        .build()
                );
    }

    @ExceptionHandler(DuplicateKeyException.class)
    public ResponseEntity<ResponseDto<Object>> handleDuplicateKey(DuplicateKeyException ex) {
        return ResponseEntity
                .status(ErrorCode.USER_ALREADY_EXISTS.getStatus())
                .body(ResponseDto.builder()
                        .success(false)
                        .message(ErrorCode.USER_ALREADY_EXISTS.getMessage())
                        .data(null)
                        .errorCode(ErrorCode.USER_ALREADY_EXISTS)
                        .build());
    }
}

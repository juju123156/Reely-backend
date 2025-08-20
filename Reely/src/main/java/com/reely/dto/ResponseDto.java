package com.reely.dto;

import com.reely.common.enums.ErrorCode;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Builder
@NoArgsConstructor
@AllArgsConstructor
@Getter
public class ResponseDto<T> {
    private boolean success;
    private String message;
    private T data;
    private ErrorCode errorCode; // 에러 발생 시 코드 포함 success 반드시 false일 때만
}

package com.reely.common.enums;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import lombok.Getter;

@Getter
public enum SMSAuthType {
    JOIN("join"),
    FIND_ID("find-id"),
    RESET_PWD("reset-pwd");

    private final String value;

    SMSAuthType(String value) {
        this.value = value;
    }

    @JsonCreator
    public static SMSAuthType from(String value) {
        for (SMSAuthType code : values()) {
            if (code.value.equalsIgnoreCase(value)) {
                return code;
            }
        }
        throw new CustomException(ErrorCode.INVALID_INPUT);
    }

}

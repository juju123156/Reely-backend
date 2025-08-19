package com.reely.dto;

import com.reely.common.enums.SMSAuthType;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class EmailDto {
    @NotBlank(message = "이메일은 필수입니다.")
    @Email(message = "올바른 이메일 형식이 아닙니다.")
    private String email;

    @Size(min = 6, message = "인증번호는 6자 이상입니다.")
    private String code;

    private SMSAuthType authType;
}

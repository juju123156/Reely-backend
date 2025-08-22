package com.reely.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class MemberDto {
    private Long memberPk;

    @NotBlank(message = "아이디는 필수입니다.")
    private String memberId;

    @NotBlank(message = "비밀번호는 필수입니다.")
    @Size(min = 8, message = "비밀번호는 8자 이상이어야 합니다.")
    private String memberPwd;

    @NotBlank(message = "이메일은 필수입니다.")
    @Email(message = "올바른 이메일 형식이 아닙니다.")
    private String memberEmail;

    private String memberNm;
    private String memberGender;
    private String memberBirth;
    private String snsYn;
    private String fileId;
    private char delYn;
    private String role;
}

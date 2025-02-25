package com.reely.dto;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class MemberDto {
    private String memberPk;
    private String memberPwd;
    private String memberEmail;
    private String memberNm;
    private String memberId;
    private String memberGender;
    private String memberBirth;
    private String snsYn;
    private String fileId;
    private char delYn;
    private String role;
}

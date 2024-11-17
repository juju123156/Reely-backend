package com.reely.dto;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class MemberDto {
    private String memberPwd;
    private String memberEmail;
    private String memberNm;
    private String memberId;
    private String memberGender;
    private String memberBirth;
    private String snsYn;
    private String fileId;
}

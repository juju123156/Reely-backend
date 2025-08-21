package com.reely.service;

import com.reely.dto.EmailDto;
import com.reely.dto.MemberDto;
import jakarta.validation.Valid;

public interface MemberService {
    Boolean existsByMemberId(MemberDto memberDto);

    Integer insertMember(MemberDto memberDto);

    Boolean existsByMemberEmail(MemberDto memberDto);

    MemberDto findMemberIdByMemberEmail(EmailDto emailDto);

    Boolean updateMemberPwdByMemberEmail(MemberDto memberDto);
}

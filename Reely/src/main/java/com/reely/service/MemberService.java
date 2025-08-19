package com.reely.service;

import com.reely.dto.EmailDto;
import com.reely.dto.MemberDto;
import jakarta.validation.Valid;

public interface MemberService {
    Boolean findMemberByMemberId(MemberDto memberDto);

    Integer insertMember(MemberDto memberDto);

    Boolean findMemberByMemberEmail(MemberDto memberDto);

    MemberDto findMemberIdByMemberEmail(EmailDto emailDto);
}

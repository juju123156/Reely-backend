package com.reely.service;

import com.reely.dto.MemberDto;

public interface MemberService {
    Boolean findMemberByMemberId(MemberDto memberDto);

    Integer insertMember(MemberDto memberDto);

    Boolean findMemberByMemberEmail(MemberDto memberDto);
}

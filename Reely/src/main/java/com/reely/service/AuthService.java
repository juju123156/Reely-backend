package com.reely.service;

import com.reely.dto.MemberDto;

import java.util.List;

public interface AuthService {
    List<MemberDto> findAll();

    Integer insertMember(MemberDto memberDto);

    MemberDto findMemberInfo(MemberDto memberDto);
}

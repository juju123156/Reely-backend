package com.reely.serviceImpl;

import com.reely.dto.MemberDto;
import com.reely.mapper.MemberMapper;
import com.reely.service.MemberService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class MemberServiceImpl implements MemberService {

    private final MemberMapper memberMapper;

    @Autowired
    public MemberServiceImpl(MemberMapper memberMapper) {this.memberMapper = memberMapper;}

    @Override
    public Boolean findMemberByMemberId(MemberDto memberDto) {
        return memberMapper.findMemberByMemberId(memberDto);
    }
}

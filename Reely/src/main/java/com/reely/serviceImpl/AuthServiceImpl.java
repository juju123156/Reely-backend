package com.reely.serviceImpl;

import com.reely.mapper.MemberMapper;
import com.reely.dto.MemberDto;
import com.reely.service.AuthService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class AuthServiceImpl implements AuthService {

    private final MemberMapper memberMapper;

    @Autowired
    public AuthServiceImpl(MemberMapper memberRepository) {
        this.memberMapper = memberRepository;
    }

    @Override
    public List<MemberDto> findAll() {
        return memberMapper.findAll();
    }

    @Override
    public Integer insertMember(MemberDto memberDto) {
        return memberMapper.insertMember(memberDto);
    }

    @Override
    public MemberDto findMemberInfo(MemberDto memberDto) {
        return memberMapper.findMemberInfo(memberDto);
    }
}
